"""Input size and shape limits (docs/THREAT_MODEL.md, D: huge inputs, zip and decompression bombs).

Pure checks with no parsing of untrusted content beyond fixed-size headers:

* byte caps per input type (URL 4 KB, message 8 KB, email 2 MB, image 5 MB);
* strict UTF-8 decoding that reports invalid input instead of crashing;
* MIME nesting / part-count pre-scan that runs *before* a recursive email parser sees the bytes;
* image header check that reads the declared pixel dimensions (PNG, GIF, JPEG, WebP) and rejects
  decompression bombs before any decoder allocates the bitmap.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import Literal

InputKind = Literal["url", "message", "email", "image"]

MAX_BYTES: dict[InputKind, int] = {
    "url": 4 * 1024,
    "message": 8 * 1024,
    "email": 2 * 1024 * 1024,
    "image": 5 * 1024 * 1024,
}
MAX_MIME_DEPTH = 8
MAX_MIME_PARTS = 64
MAX_IMAGE_PIXELS = 25_000_000  # 5000 x 5000; a 5 MB PNG declaring more is a decompression bomb
MAX_IMAGE_SIDE = 16_384


@dataclass(frozen=True, slots=True)
class LimitResult:
    ok: bool
    reason: str | None = None  # too_large | invalid_utf8 | mime_too_deep | mime_too_many_parts | image_*
    detail: dict[str, int | str] | None = None


OK = LimitResult(True)


def check_size(kind: InputKind, data: bytes | str) -> LimitResult:
    n = len(data.encode("utf-8", "surrogatepass")) if isinstance(data, str) else len(data)
    cap = MAX_BYTES[kind]
    if n > cap:
        return LimitResult(False, "too_large", {"bytes": n, "max_bytes": cap})
    return OK


def decode_text(data: bytes) -> tuple[str, bool]:
    """Decode UTF-8. Invalid sequences become U+FFFD; the flag says the input was not valid UTF-8."""
    try:
        return data.decode("utf-8"), False
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), True


_CT_RE = re.compile(rb"(?im)^content-type:[ \t]*multipart/[^\r\n]*(?:\r?\n[ \t][^\r\n]*)*")
_BOUNDARY_RE = re.compile(rb'(?i)boundary\s*=\s*(?:"([^"\r\n]{1,200})"|([^;\s\r\n]{1,200}))')


def check_mime(raw: bytes) -> LimitResult:
    """Pre-scan an email for multipart nesting depth and part count without a recursive parser.

    Depth is computed from the order of boundary declarations and their delimiter lines: a
    boundary declared inside an open part of another boundary is one level deeper.
    """
    size = check_size("email", raw)
    if not size.ok:
        return size
    boundaries: list[bytes] = []
    for m in _CT_RE.finditer(raw):
        b = _BOUNDARY_RE.search(m.group())
        if b:
            boundaries.append(b.group(1) or b.group(2))
            if len(boundaries) > MAX_MIME_PARTS:
                return LimitResult(False, "mime_too_many_parts", {"multipart_containers": len(boundaries)})
    parts = 0
    for b in set(boundaries):
        parts += raw.count(b"\n--" + b) + (1 if raw.startswith(b"--" + b) else 0)
        if parts > MAX_MIME_PARTS * 4:
            return LimitResult(False, "mime_too_many_parts", {"delimiters": parts})
    depth = _mime_depth(raw, boundaries)
    if depth > MAX_MIME_DEPTH:
        return LimitResult(False, "mime_too_deep", {"depth": depth, "max_depth": MAX_MIME_DEPTH})
    return OK


def _mime_depth(raw: bytes, boundaries: list[bytes]) -> int:
    # Each multipart container nests inside the container whose boundary was most recently opened
    # and not yet closed (``--b--``). Track that with a stack over declaration / delimiter events.
    events: list[tuple[int, int, bytes]] = []  # (offset, kind, boundary) kind 0=declare 1=close
    pos = 0
    for b in boundaries:
        i = raw.find(b, pos)
        if i < 0:
            continue
        events.append((i, 0, b))
        pos = i + len(b)
        close = raw.find(b"--" + b + b"--", pos)
        if close >= 0:
            events.append((close, 1, b))
    events.sort()
    stack: list[bytes] = []
    deepest = 0
    for _off, kind, b in events:
        if kind == 0:
            stack.append(b)
            deepest = max(deepest, len(stack))
        elif b in stack:
            while stack and stack.pop() != b:
                pass
    return deepest


@dataclass(frozen=True, slots=True)
class ImageHeader:
    format: str
    width: int
    height: int


def image_header(data: bytes) -> ImageHeader | None:
    """Declared dimensions from the first bytes of a PNG, GIF, JPEG or WebP. None if unknown."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24 and data[12:16] == b"IHDR":
        w, h = struct.unpack(">II", data[16:24])
        return ImageHeader("png", w, h)
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        w, h = struct.unpack("<HH", data[6:10])
        return ImageHeader("gif", w, h)
    if data[:2] == b"\xff\xd8":
        return _jpeg(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            w = 1 + int.from_bytes(data[24:27], "little")
            h = 1 + int.from_bytes(data[27:30], "little")
            return ImageHeader("webp", w, h)
        if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", data[26:30])
            return ImageHeader("webp", w & 0x3FFF, h & 0x3FFF)
        if chunk == b"VP8L" and data[20:21] == b"\x2f":
            bits = int.from_bytes(data[21:25], "little")
            return ImageHeader("webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    return None


_SOF = frozenset([0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF])


def _jpeg(data: bytes) -> ImageHeader | None:
    i = 2
    n = min(len(data), 512 * 1024)  # SOF is always near the start; never scan the whole file
    while i + 9 < n:
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in _SOF:
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return ImageHeader("jpeg", w, h)
        if seg_len < 2:
            return None
        i += 2 + seg_len
    return None


def check_image(data: bytes) -> LimitResult:
    size = check_size("image", data)
    if not size.ok:
        return size
    hdr = image_header(data)
    if hdr is None:
        return LimitResult(False, "image_unknown_format")
    if hdr.width == 0 or hdr.height == 0:
        return LimitResult(False, "image_zero_dimension", {"format": hdr.format})
    pixels = hdr.width * hdr.height
    if hdr.width > MAX_IMAGE_SIDE or hdr.height > MAX_IMAGE_SIDE or pixels > MAX_IMAGE_PIXELS:
        return LimitResult(
            False,
            "image_decompression_bomb",
            {"format": hdr.format, "width": hdr.width, "height": hdr.height, "max_pixels": MAX_IMAGE_PIXELS},
        )
    return OK
