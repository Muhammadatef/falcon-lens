"""Bounded decoding of encoded payloads hidden in untrusted text.

Finds base64 / base64url, hex, percent-encoded and HTML-entity runs, decodes them (never executes
anything) and returns the decoded text with the source span, so the detector can scan the decoded
form and ``neutralise`` can remove the encoded blob. ROT13 is handled by the detector as a whole-text
transform. All work is capped (blob count, blob size, total decoded bytes, one nesting level).
"""

from __future__ import annotations

import base64
import binascii
import codecs
import html
import re
from dataclasses import dataclass
from urllib.parse import unquote

MAX_BLOBS = 24
MAX_BLOB_CHARS = 8192
MAX_DECODED_TOTAL = 64 * 1024

_B64_RE = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{16,}={0,2}(?![A-Za-z0-9+/=_-])")
_HEX_RE = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){16,}(?![0-9A-Fa-f])")
_PCT_RE = re.compile(r"(?:%[0-9A-Fa-f]{2}){6,}")
_ENT_RE = re.compile(r"(?:&#(?:x[0-9A-Fa-f]{1,6}|[0-9]{1,7});\s?){6,}")


@dataclass(frozen=True, slots=True)
class Decoded:
    start: int
    end: int
    text: str
    encoding: str  # base64 | hex | percent | entity


def _printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    good = sum(1 for c in s if c.isprintable() or c in "\n\t")
    return good / len(s)


def _as_text(raw: bytes) -> str | None:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(s) < 6 or _printable_ratio(s) < 0.9 or not re.search(r"[A-Za-z؀-ۿ]{3}", s):
        return None
    return s


def _b64(blob: str) -> str | None:
    if blob.isdigit() or blob.isalpha() and (blob.islower() or blob.isupper()):
        return None  # plain words / numbers, not base64
    s = blob.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        return None
    return _as_text(raw)


def find_encoded(text: str) -> list[Decoded]:
    out: list[Decoded] = []
    total = 0

    def add(start: int, end: int, decoded: str | None, enc: str) -> None:
        nonlocal total
        if decoded is None or len(out) >= MAX_BLOBS or total >= MAX_DECODED_TOTAL:
            return
        decoded = decoded[: MAX_DECODED_TOTAL - total]
        total += len(decoded)
        out.append(Decoded(start, end, decoded, enc))
        # one nested level: base64 inside base64, entities inside percent-encoding, ...
        for inner in _scan_once(decoded):
            if len(out) < MAX_BLOBS and total < MAX_DECODED_TOTAL:
                total += len(inner.text)
                out.append(Decoded(start, end, inner.text, f"{enc}+{inner.encoding}"))

    for m in _B64_RE.finditer(text):
        if len(m.group()) <= MAX_BLOB_CHARS:
            add(m.start(), m.end(), _b64(m.group()), "base64")
    for m in _HEX_RE.finditer(text):
        if len(m.group()) <= MAX_BLOB_CHARS:
            add(m.start(), m.end(), _as_text(bytes.fromhex(m.group())), "hex")
    for m in _PCT_RE.finditer(text):
        add(m.start(), m.end(), unquote(m.group(), errors="replace"), "percent")
    for m in _ENT_RE.finditer(text):
        add(m.start(), m.end(), html.unescape(m.group()), "entity")
    return out


def _scan_once(text: str) -> list[Decoded]:
    out: list[Decoded] = []
    for m in _B64_RE.finditer(text[:MAX_BLOB_CHARS]):
        d = _b64(m.group())
        if d is not None:
            out.append(Decoded(m.start(), m.end(), d, "base64"))
    if "&#" in text:
        un = html.unescape(text)
        if un != text:
            out.append(Decoded(0, len(text), un, "entity"))
    return out[:4]


def rot13(text: str) -> str:
    return codecs.decode(text, "rot13")
