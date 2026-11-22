# ruff: noqa: E501
"""Arabic and Arabizi normalisation with an index map back to the original text.

``normalize`` keeps, for each output char, the index of the original char it came from, so rule spans can
be reported as offsets into the user's original text (never the text itself).
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

MAX_MESSAGE_CHARS = 8192  # THREAT_MODEL: message limit 8 KB

_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")} | {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
_FOLD = {
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",  # alef variants
    "ى": "ي",
    "ی": "ي",
    "ئ": "ي",  # yaa / alef maqsura / Persian yeh
    "ة": "ه",  # taa marbuta
    "ؤ": "و",
    "ک": "ك",  # Persian kaf
    "،": ",",
    "؛": ";",
    "؟": "?",
}
_DROP_RANGES = ((0x0610, 0x061A), (0x064B, 0x065F), (0x0670, 0x0670), (0x06D6, 0x06ED))
_DROP = frozenset("ـ\u200b‌‍⁠﻿­\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\u061c")


@dataclass(frozen=True)
class Normalized:
    text: str
    index_map: tuple[int, ...]  # index_map[i] = original index of text[i]

    def original_span(self, start: int, end: int, original_len: int) -> tuple[int, int]:
        if not self.index_map:
            return (0, 0)
        s = self.index_map[start]
        e = self.index_map[end - 1] + 1 if end > start else s
        return (s, min(e, original_len))


def _dropped(ch: str) -> bool:
    if ch in _DROP:
        return True
    o = ord(ch)
    return any(a <= o <= b for a, b in _DROP_RANGES)


def normalize(text: str, collapse: bool = True) -> Normalized:
    """Fold alef/yaa/taa-marbuta, drop diacritics, tatweel and invisibles, Arabic-Indic digits to ASCII,
    casefold (1->n expansions such as İ or ß map every output char to its source char), collapse whitespace
    and, when ``collapse`` is set, runs of the same letter to ONE letter (elongation; lexicons are collapsed
    the same way so both sides meet)."""
    out: list[str] = []
    idx: list[int] = []
    for i, raw in enumerate(text):
        for ch0 in unicodedata.normalize("NFKC", raw):
            if _dropped(ch0):
                continue
            ch0 = ch0.translate(_DIGITS)
            for ch in _FOLD.get(ch0, ch0).casefold():
                if _dropped(ch):
                    continue
                if ch.isspace():
                    if not out or out[-1] == " ":
                        continue
                    ch = " "
                elif collapse and ch.isalpha() and out and out[-1] == ch:
                    continue
                out.append(ch)
                idx.append(i)
    return Normalized("".join(out), tuple(idx))


# Arabizi digit-letters: 2 hamza/alef, 3 ayn, 5 kha, 7 ha, 9 qaf. Folded to single ASCII letters (length
# preserving) so lexicon terms and text meet in one space. Only digits inside a word that also has a
# letter are folded ("3ajil", "7esab"), never standalone numbers.
_AZ = {"2": "a", "3": "a", "5": "k", "7": "h", "9": "q"}


def arabizi_fold(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i].isascii() and s[i].isalnum():
            j = i
            while j < n and s[j].isascii() and s[j].isalnum():
                j += 1
            tok = s[i:j]
            if any(c.isalpha() for c in tok):
                tok = "".join(_AZ.get(c, c) for c in tok)
            out.append(tok)
            i = j
        else:
            out.append(s[i])
            i += 1
    return "".join(out)
