"""Text normalisation shared by the page classifiers (English + Arabic)."""

from __future__ import annotations

import re
import unicodedata

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SEP = re.compile(r"[^0-9a-z؀-ۿ]+")
_ARABIC_MARKS = re.compile(r"[ً-ٰٟـ]")  # harakat, superscript alef, tatweel
_ALEF = str.maketrans(
    {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}
)
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalize(text: str) -> str:
    """Split camelCase and separators, lower-case, fold Arabic letter variants and digits.

    The result is space-padded, so ``f" {word} " in normalize(x)`` is a whole-word test.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = _CAMEL.sub(" ", text)
    text = text.lower()
    text = _ARABIC_MARKS.sub("", text).translate(_ALEF).translate(_ARABIC_DIGITS)
    return " " + _SEP.sub(" ", text).strip() + " "
