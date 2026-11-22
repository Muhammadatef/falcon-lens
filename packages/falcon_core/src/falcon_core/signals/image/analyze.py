# ruff: noqa: E501
"""Image pipeline (deterministic): magic-byte validation, decompression-bomb limit, QR decoding.

OCR is NOT done here: it belongs to the quarantined vision extractor. ``OcrHook`` is the seam; the caller
passes an async callable and feeds the returned text into the message pipeline.

QR library: zxing-cpp (``zxing-cpp`` on PyPI). It ships binary wheels for macOS arm64 and manylinux
x86_64/aarch64 with no system libraries (pyzbar needs libzbar). Version recorded in DECISIONS.md.
"""

from __future__ import annotations

import io
import warnings
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.message.extract import ChildInput, extract_urls
from falcon_core.signals.url.textutil import defang

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # THREAT_MODEL: image limit 5 MB
MAX_PIXELS = 25_000_000  # decompression-bomb limit (width*height)
MAX_QR = 5

OcrHook = Callable[[bytes], Awaitable[str | None]]
"""Hook for the quarantined vision extractor: image bytes -> extracted text (or None)."""

SPEC = SignalSpec(
    name="image.analyze",
    family="image",
    tier="T1",
    input_types=("image",),
    timeout_ms=2000,
    network="none",
    emits=("image.invalid", "image.qr_decoded"),
)


def sniff(data: bytes) -> str | None:
    """Image type from magic bytes only (never the filename or declared content type)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


@dataclass
class ImageAnalysis:
    evidence: list[Evidence] = field(default_factory=list)
    children: list[ChildInput] = field(default_factory=list)
    kind: str | None = None
    needs_ocr: bool = False  # True when the image is valid: caller may run its OcrHook


def _invalid(reason: str) -> Evidence:
    return Evidence(
        signal="image.invalid",
        family="image",
        polarity="neutral",
        observed={"reason": reason},
        display={"en": "Image could not be processed safely", "ar": "تعذرت معالجة الصورة بأمان"},
    )


def analyze_image(data: bytes) -> ImageAnalysis:
    from PIL import Image, UnidentifiedImageError

    res = ImageAnalysis()
    if len(data) > MAX_IMAGE_BYTES:
        res.evidence.append(_invalid("too_large"))
        return res
    kind = sniff(data)
    if kind is None:
        res.evidence.append(_invalid("bad_magic"))
        return res
    res.kind = kind
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            prev, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, MAX_PIXELS
            try:
                img = Image.open(io.BytesIO(data))  # lazy: header only
                if img.format is None or img.format.lower() != kind:
                    res.evidence.append(_invalid("format_mismatch"))
                    return res
                if img.width * img.height > MAX_PIXELS:
                    res.evidence.append(_invalid("pixel_limit"))
                    return res
                img.load()
                rgb = img.convert("RGB")
            finally:
                Image.MAX_IMAGE_PIXELS = prev
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        res.evidence.append(_invalid("pixel_limit"))
        return res
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        res.evidence.append(_invalid("decode_error"))
        return res
    res.needs_ocr = True
    payloads = _decode_qr(rgb)
    urls: list[ChildInput] = []
    for p in payloads:
        urls += [ChildInput("url", u.value, None, "image.qr") for u in extract_urls(p)]
    if payloads:
        res.children = urls
        res.evidence.append(
            Evidence(
                signal="image.qr_decoded",
                family="image",
                polarity="neutral",
                observed={
                    "qr_count": len(payloads),
                    "urls": [defang(u.value)[:200] for u in urls[:5]],
                },
                display={"en": "QR code found in image", "ar": "تم العثور على رمز QR في الصورة"},
            )
        )
    return res


def _decode_qr(rgb: object) -> list[str]:
    import zxingcpp

    out: list[str] = []
    for r in zxingcpp.read_barcodes(rgb, formats=zxingcpp.BarcodeFormat.QRCode):  # type: ignore[arg-type]
        if r.text and r.text not in out:
            out.append(r.text[:2048])
        if len(out) >= MAX_QR:
            break
    return out


async def analyze_image_with_ocr(
    data: bytes, ocr: OcrHook | None = None
) -> tuple[ImageAnalysis, str | None]:
    """analyze_image plus the OCR hook. The returned text is untrusted; route it to the message pipeline."""
    res = analyze_image(data)
    text = await ocr(data) if (ocr and res.needs_ocr) else None
    return res, text


@signal(SPEC)
def run_image(ctx: SignalContext) -> list[Evidence]:
    data = getattr(ctx, "data", None)
    return analyze_image(data).evidence if isinstance(data, bytes) else []
