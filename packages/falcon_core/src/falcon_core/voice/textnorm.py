"""Arabic/English text folding shared by the voice intent rules."""

from __future__ import annotations

import re
import unicodedata

MAX_CHARS = 300

_MARKS = re.compile("[ً-ٰٟـ]")  # diacritics + tatweel
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ئ": "ي", "ؤ": "و"})
_TOKEN = re.compile("[\\wً-ٰٟـ']+")


def norm_word(word: str) -> str:
    """Lowercase, NFKC, no diacritics/tatweel, alef/yeh/teh-marbuta folded, no punctuation."""
    w = unicodedata.normalize("NFKC", word).lower()
    w = _MARKS.sub("", w).translate(_FOLD)
    return "".join(ch for ch in w if ch.isalnum())


def normalise(text: str) -> str:
    """Normalised text with single spaces (punctuation becomes a space)."""
    return " ".join(t for t in (norm_word(m.group()) for m in _TOKEN.finditer(text)) if t)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
