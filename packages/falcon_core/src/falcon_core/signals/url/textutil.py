# ruff: noqa: E501
"""Small pure helpers shared by the URL signals."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

BIDI_CHARS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
ZERO_WIDTH_CHARS = frozenset(
    "\u200b\u200c\u200d\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad\u180e\u034f"
)
_ARABIC_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭـ]")  # tashkeel, tatweel
_SEP = re.compile(r"[\s\-_.\u200c\u200d]+")


def defang(value: str) -> str:
    """Defang a host/URL for evidence output (CLAUDE.md: publish only defanged URLs)."""
    v = value.replace("http://", "hxxp://").replace("https://", "hxxps://")
    return v.replace(".", "[.]")[:512]


def normalize_arabic(s: str) -> str:
    """Fold alef/hamza variants, ya/alef-maqsura, remove tashkeel/tatweel; lowercase Latin."""
    s = unicodedata.normalize("NFKC", s)
    s = _ARABIC_DIACRITICS.sub("", s)
    for a in "أإآٱ":
        s = s.replace(a, "ا")
    s = s.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    return s.casefold()


def compact(s: str) -> str:
    """Normalised text with separators (space, hyphen, dot, underscore) removed."""
    return _SEP.sub("", normalize_arabic(s))


def script_of(ch: str) -> str | None:
    """Coarse script name via the Unicode character name; None for Common/Inherited (digits, '-', '.')."""
    if ch.isdigit() or ch in "-._":
        return None
    cat = unicodedata.category(ch)
    if cat.startswith(("M", "P", "S", "Z", "C")):
        return None
    try:
        first = unicodedata.name(ch).split()[0]
    except ValueError:
        return None
    return first


def scripts_in(s: str) -> set[str]:
    return {sc for ch in s if (sc := script_of(ch)) is not None}


def entropy(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def strip_invisible(s: str) -> str:
    return "".join(c for c in s if c not in BIDI_CHARS and c not in ZERO_WIDTH_CHARS)


def damerau_osa(a: str, b: str, limit: int = 3) -> int:
    """Optimal-string-alignment (restricted Damerau-Levenshtein) distance; returns limit+1 if above limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    if a == b:
        return 0
    la, lb = len(a), len(b)
    prev2: list[int] = []
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                v = min(v, prev2[j - 2] + 1)
            cur[j] = v
            row_min = min(row_min, v)
        if row_min > limit:
            return limit + 1
        prev2, prev = prev, cur
    return min(prev[lb], limit + 1)


_ROWS = ["qwertyuiop", "asdfghjkl", "zxcvbnm"]
_POS = {c: (r, i + (0.5 * r)) for r, row in enumerate(_ROWS) for i, c in enumerate(row)}


def keys_adjacent(x: str, y: str) -> bool:
    """QWERTY neighbourhood (same/adjacent row, horizontal offset < 1.2)."""
    if x == y or x not in _POS or y not in _POS:
        return False
    (r1, c1), (r2, c2) = _POS[x], _POS[y]
    return abs(r1 - r2) <= 1 and abs(c1 - c2) < 1.2


def all_subs_adjacent(a: str, b: str) -> bool:
    """Equal length and every differing position is a keyboard-adjacent substitution."""
    if len(a) != len(b) or a == b:
        return False
    return all(x == y or keys_adjacent(x, y) for x, y in zip(a, b, strict=True))
