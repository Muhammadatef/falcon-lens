"""Offset-preserving normalisation for the injection detector.

Every output character remembers the index of the original character it came from, so a pattern
match on the normalised text can be mapped back to a span of the original text (``neutralise``).

Steps, per character: drop zero-width / bidi / soft-hyphen / variation selectors; NFKC (full-width
and mathematical letters fold to ASCII); fold common Cyrillic/Greek homoglyphs to Latin; drop
Arabic diacritics and tatweel; unify Arabic letter variants (alef, ya, ta marbuta); lowercase;
collapse whitespace runs to one space.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

# Zero-width, bidi controls, BOM, soft hyphen, word joiner, invisible operators, variation selectors.
_INVISIBLE = frozenset(
    [0x00AD, 0x034F, 0x061C, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180E, 0x3164, 0xFEFF, 0xFFA0]
    + list(range(0x200B, 0x2010))
    + list(range(0x202A, 0x202F))
    + list(range(0x2060, 0x2070))
    + list(range(0xFE00, 0xFE10))
)
BIDI_CONTROLS = frozenset([0x061C, 0x200E, 0x200F, *range(0x202A, 0x202F), *range(0x2066, 0x206A)])
ZERO_WIDTH = frozenset([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD])

# Confusables that NFKC keeps (Cyrillic / Greek letters that look Latin).
_HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "ɡ": "g", "һ": "h", "ӏ": "l", "ո": "n", "ս": "u", "ν": "v", "ο": "o",
    "α": "a", "ε": "e", "ι": "i", "κ": "k", "τ": "t", "ρ": "p", "υ": "u", "χ": "x", "Ꭺ": "a",
    "А": "a", "В": "b", "Е": "e", "К": "k", "М": "m", "Н": "h", "О": "o", "Р": "p", "С": "c",
    "Т": "t", "Х": "x", "Ү": "y", "Ι": "i", "Α": "a", "Β": "b", "Ε": "e", "Κ": "k", "Μ": "m",
    "Ν": "n", "Ο": "o", "Ρ": "p", "Τ": "t", "Χ": "x", "Υ": "y", "Ζ": "z",
}  # fmt: skip

_ARABIC_FOLD = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ؤ": "و", "ة": "ه", "ک": "ك", "ی": "ي"}
_TATWEEL = "ـ"


def _is_arabic_mark(ch: str) -> bool:
    o = ord(ch)
    return 0x064B <= o <= 0x065F or o == 0x0670 or 0x06D6 <= o <= 0x06ED


@dataclass(frozen=True, slots=True)
class Normalised:
    text: str
    origin: tuple[int, ...]  # origin[i] = index in the source text of normalised char i
    invisible: int  # number of zero-width / bidi characters dropped
    bidi: int
    homoglyphs: int  # number of confusable letters folded

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Map a normalised [start, end) span back to the source text."""
        if not self.origin or start >= len(self.origin):
            return (0, 0)
        end = max(start + 1, min(end, len(self.origin)))
        return (self.origin[start], self.origin[end - 1] + 1)


def normalise(text: str) -> Normalised:
    out: list[str] = []
    origin: list[int] = []
    invisible = bidi = homo = 0
    last_space = True
    for i, ch in enumerate(text):
        o = ord(ch)
        if o in _INVISIBLE:
            invisible += 1
            if o in BIDI_CONTROLS:
                bidi += 1
            continue
        if ch == _TATWEEL or _is_arabic_mark(ch):
            continue
        for c in unicodedata.normalize("NFKC", ch).lower():
            if c in _HOMOGLYPHS:
                c = _HOMOGLYPHS[c]
                homo += 1
            c = _ARABIC_FOLD.get(c, c)
            if unicodedata.category(c) == "Mn":  # combining marks left over from NFKC
                continue
            if c.isspace() or unicodedata.category(c) in ("Zs", "Cc"):
                if last_space:
                    continue
                c = " "
                last_space = True
            else:
                last_space = False
            out.append(c)
            origin.append(i)
    return Normalised("".join(out), tuple(origin), invisible, bidi, homo)
