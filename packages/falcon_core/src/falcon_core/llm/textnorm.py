"""Unicode normalisation applied before redaction, spotlighting, canary and verifier checks.

``normalise_text``:
1. NFKC (full-width digits/letters/``＠``/``．``, Arabic presentation forms -> base letters);
2. U+0085, U+2028, U+2029, VT, FF, CR and CRLF -> ``\\n``;
3. removes every format character (category ``Cf``: zero-width, bidi controls, soft hyphen,
   U+180E, U+2061-2064, the U+E0000 tag block, BOM);
4. maps every decimal digit (Arabic-Indic, extended Arabic-Indic, Devanagari, ...) to ASCII;
5. maps ideographic / half-width full stops to ``.``.

The function is idempotent.
"""

from __future__ import annotations

import re
import unicodedata

_LINE_SEP_RE = re.compile("\r\n|[\r\x0b\x0c\x85\u2028\u2029]")
_DOTS = str.maketrans({"。": ".", "｡": ".", "﹒": "."})


def _fold_char(c: str) -> str:
    if c.isascii():
        return c
    if unicodedata.category(c) == "Cf":
        return ""
    if c.isdecimal():
        return str(unicodedata.decimal(c))
    return c


def normalise_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _LINE_SEP_RE.sub("\n", text)
    text = "".join(_fold_char(c) for c in text)
    return text.translate(_DOTS)
