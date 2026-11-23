"""PII redaction applied before any cloud LLM call and before logging (docs/PRIVACY.md).

The text is first normalised (``textnorm.normalise_text``: NFKC, format/zero-width/bidi/tag
characters removed, Arabic-Indic and other Unicode digits mapped to ASCII, Unicode line
separators folded), and the *normalised* text is what gets redacted and returned. So a ZWSP or
Arabic-Indic digits cannot hide a number from the patterns, and the caller only ever forwards the
redacted normalised text.

Covers UAE phone numbers (+971 / 00971 / 05x), Emirates ID (784-YYYY-NNNNNNN-N), card numbers
(Luhn-checked, 13-19 digits), e-mail addresses and UAE IBANs (AE + 21 digits). Separators may be
space, ``-`` or ``.``. Order matters: e-mail and IBAN first, then Emirates ID (its 15 digits can pass
Luhn), then cards, then phones.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from falcon_core.llm.textnorm import normalise_text

PLACEHOLDERS = {
    "email": "[EMAIL]",
    "iban": "[IBAN]",
    "emirates_id": "[EMIRATES_ID]",
    "card": "[CARD]",
    "phone": "[PHONE]",
}

_S = r"[ .\-]?"  # one optional separator
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+\s*@\s*[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}", re.ASCII)
_IBAN_RE = re.compile(rf"(?<![A-Za-z0-9])AE{_S}[0-9]{{2}}(?:{_S}[0-9]){{19}}(?![0-9])", re.IGNORECASE | re.ASCII)
_EID_RE = re.compile(rf"(?<![0-9])784{_S}[0-9]{{4}}{_S}[0-9]{{7}}{_S}[0-9](?![0-9])", re.ASCII)
_CARD_CANDIDATE_RE = re.compile(rf"(?<![0-9])[0-9](?:{_S}[0-9]){{12,18}}(?![0-9])", re.ASCII)
# +971 / 00971 / 971, optional trunk 0, mobile 5x or landline area code 2-9, then 7 digits.
_PHONE_INTL_RE = re.compile(
    rf"(?<![0-9+])(?:\+|00)?971{_S}\(?0?\)?{_S}(?:5[0-9]|[2-9]){_S}[0-9]{{3}}{_S}[0-9]{{4}}(?![0-9])", re.ASCII
)
# Local mobile 05x xxx xxxx.
_PHONE_LOCAL_RE = re.compile(rf"(?<![0-9])05[0-9]{_S}[0-9]{{3}}{_S}[0-9]{{4}}(?![0-9])", re.ASCII)


def luhn_ok(digits: str) -> bool:
    """Luhn checksum over a digit string."""
    if not digits or not digits.isascii() or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return any(self.counts.values())


def _sub(
    pattern: re.Pattern[str],
    kind: str,
    text: str,
    counts: Counter[str],
    accept: Callable[[str], bool] | None = None,
) -> str:
    def repl(m: re.Match[str]) -> str:
        if accept is not None and not accept(m.group(0)):
            return m.group(0)
        counts[kind] += 1
        return PLACEHOLDERS[kind]

    return pattern.sub(repl, text)


def _is_card(candidate: str) -> bool:
    digits = re.sub(r"[^0-9]", "", candidate)
    return 13 <= len(digits) <= 19 and luhn_ok(digits)


def redact(text: str) -> RedactionResult:
    """Normalise, then replace PII with placeholders. Returns the normalised redacted text."""
    counts: Counter[str] = Counter()
    out = _sub(_EMAIL_RE, "email", normalise_text(text), counts)
    out = _sub(_IBAN_RE, "iban", out, counts)
    out = _sub(_EID_RE, "emirates_id", out, counts)
    out = _sub(_CARD_CANDIDATE_RE, "card", out, counts, accept=_is_card)
    out = _sub(_PHONE_INTL_RE, "phone", out, counts)
    out = _sub(_PHONE_LOCAL_RE, "phone", out, counts)
    return RedactionResult(out, dict(counts))


def redact_text(text: str) -> str:
    """Convenience: redacted text only (for log fields)."""
    return redact(text).text
