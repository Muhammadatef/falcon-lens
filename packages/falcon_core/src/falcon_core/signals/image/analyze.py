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
from falcon_core.signals.url.display import display_url
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
    extra_content: bool = False  # True when substantial non-QR content (likely printed text) surrounds the QR


def _invalid(reason: str) -> Evidence:
    return Evidence(
        signal="image.invalid",
        family="image",
        polarity="neutral",
        observed={"reason": reason},
        display={"en": "Image could not be processed", "ar": "تعذرت معالجة الصورة"},
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
    payloads, boxes = _decode_qr(rgb)
    if payloads:
        res.extra_content = _substantial_outside(rgb, boxes)
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
                    "urls": [defang(display_url(u.value))[:200] for u in urls[:5]],
                },
                display={"en": "QR code found in image", "ar": "تم العثور على رمز QR في الصورة"},
            )
        )
    return res


MAX_OUTSIDE_INK = 0.03  # fraction of pixels that are ink outside the QR boxes
MAX_OUTSIDE_LINES = 3  # text-like row bands outside the QR boxes


def _decode_qr(rgb: object) -> tuple[list[str], list[tuple[int, int, int, int]]]:
    import zxingcpp

    out: list[str] = []
    boxes: list[tuple[int, int, int, int]] = []
    for r in zxingcpp.read_barcodes(rgb, formats=zxingcpp.BarcodeFormat.QRCode):  # type: ignore[arg-type]
        if r.text and r.text not in out:
            out.append(r.text[:2048])
            q = r.position
            xs = [q.top_left.x, q.top_right.x, q.bottom_left.x, q.bottom_right.x]
            ys = [q.top_left.y, q.top_right.y, q.bottom_left.y, q.bottom_right.y]
            boxes.append((min(xs), min(ys), max(xs), max(ys)))
        if len(out) >= MAX_QR:
            break
    return out, boxes


def _substantial_outside(rgb: object, boxes: list[tuple[int, int, int, int]]) -> bool:
    """Heuristic: is there more than a title/caption of non-QR content? Ink = pixels far from the dominant
    background colour, outside the QR boxes (plus a quiet-zone pad). Residual limit: THREAT_MODEL.md."""
    import numpy as np
    from PIL import Image

    a = np.asarray(rgb.convert("L") if isinstance(rgb, Image.Image) else rgb).astype(int)
    vals, counts = np.unique(a, return_counts=True)
    ink = np.abs(a - vals[counts.argmax()]) > 40
    for x0, y0, x1, y1 in boxes:
        pad = int(0.1 * max(x1 - x0, y1 - y0))
        ink[max(y0 - pad, 0) : y1 + pad, max(x0 - pad, 0) : x1 + pad] = False
    if ink.sum() / ink.size > MAX_OUTSIDE_INK:
        return True
    rows = ink.sum(axis=1) > 0
    bands = int(np.sum(rows[1:] & ~rows[:-1])) + int(rows[0])
    return bands > MAX_OUTSIDE_LINES


async def analyze_image_with_ocr(data: bytes, ocr: OcrHook | None = None) -> tuple[ImageAnalysis, str | None]:
    """analyze_image plus the OCR hook. The returned text is untrusted; route it to the message pipeline."""
    res = analyze_image(data)
    text = await ocr(data) if (ocr and res.needs_ocr) else None
    return res, text


@signal(SPEC)
def run_image(ctx: SignalContext) -> list[Evidence]:
    data = getattr(ctx, "data", None)
    return analyze_image(data).evidence if isinstance(data, bytes) else []
