"""Official contact numbers per brand (``official_contacts`` in data/brands.yaml) and UAE number normalisation.

Every entry is read on the entity's own page and carries ``source_url`` (https) and ``retrieved_at``; an entry
without them does not load (``ValueError``), so an incomplete registry fails loudly instead of silently trusting.
``kind: phone`` values are E.164 (``+971...``); ``kind: short_code`` values are the 3-5 digits shown (999, 101).

Normalisation (``to_e164``) maps every written form of one UAE number to the same E.164 string: Arabic-Indic and
Persian digits, spaces, dashes, dots and brackets, the ``+971`` / ``00971`` / ``971`` prefixes (with or without the
trunk ``0`` after them) and the national ``0`` prefix; toll-free ``800`` and shared-cost ``600`` numbers are also
recognised without any prefix. Pure functions, no I/O.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from falcon_core.signals.url.textutil import normalize_arabic

E164_UAE = re.compile(r"^\+971\d{6,10}$")
SHORT_CODE = re.compile(r"^\d{3,5}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGITS = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")} | {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
# A run of digit groups joined by spaces, dashes, dots or brackets, optionally led by "+" (one candidate phrase).
_RUN = re.compile(r"(?<![\w+])\+?\d[\d \t ().\-]{3,24}\d(?![\w])")
_GROUP = re.compile(r"\+?\d+")
MAX_NUMBERS = 10


@dataclass(frozen=True)
class OfficialContact:
    kind: str  # "phone" | "short_code"
    value: str  # E.164 for phone, digits for short_code
    local: str
    label_en: str
    label_ar: str
    source_url: str
    retrieved_at: str


def ascii_digits(s: str) -> str:
    return s.translate(_DIGITS)


def _national_ok(nat: str) -> bool:
    """National significant number of a UAE number: toll-free 800, shared-cost 600, mobile 5x, geographic area codes."""
    if not nat.isdigit():
        return False
    if nat.startswith("800"):
        return 6 <= len(nat) <= 10
    if nat.startswith("600"):
        return len(nat) == 9
    if nat.startswith("5"):
        return len(nat) == 9
    return nat[:1] in "234679" and len(nat) == 8


def to_e164(raw: str) -> str | None:
    """E.164 form of a written UAE number, or None when ``raw`` is not one."""
    s = ascii_digits(raw).strip()
    plus = s.startswith("+")
    d = re.sub(r"\D", "", s)
    if plus and not d.startswith("971"):
        return None
    if d.startswith("00971"):
        nat = d[5:]
    elif d.startswith("971"):
        nat = d[3:]
    elif d.startswith("0"):
        nat = d[1:]
    elif d.startswith(("800", "600")):
        nat = d
    else:
        return None
    if nat.startswith("0"):  # "+971 (0)4 ..." and "009710..." keep the trunk zero by mistake
        nat = nat[1:]
    return "+971" + nat if _national_ok(nat) else None


# Unprefixed 600/800 numbers are accepted only in the spaced or dashed form organisations print ("800 555",
# "800-4354", "600 54 0000") AND next to a phone/contact word; a bare "800412" is far more often a code or amount.
_BARE_STYLE = re.compile(r"^(?:800|600)[ \t\u00a0-]+\d")
_CONTACT_WORDS = (
    "call", "phone", "contact", "hotline", "helpline", "whatsapp", "whats app", "tel", "dial", "toll free",
    "toll-free", "customer service", "customer care", "support", "mobile",
    "اتصل", "اتصال", "الاتصال", "رقم", "هاتف", "الهاتف", "خدمة العملاء", "واتساب", "واتس", "تواصل", "الخط الساخن",
    "مركز الاتصال", "جوال",
)  # fmt: skip
# Next to these words a digit run is a code or an amount, never a phone number (any form, prefixed or not).
_NOT_PHONE_WORDS = (
    "otp", "code", "pin", "password", "passcode", "aed", "dhs", "dh", "usd", "amount",
    "رمز", "كود", "الرمز", "كلمة السر", "رقم سري", "الرقم السري", "رقم التحقق", "درهم", "د.إ", "دإ", "المبلغ", "مبلغ",
)  # fmt: skip
_CONTACT_BEFORE, _CONTACT_AFTER = 48, 24
_NOT_BEFORE, _NOT_AFTER = 16, 12


def _has_word(window: str, words: tuple[str, ...]) -> bool:
    w = normalize_arabic(window.lower())
    for word in words:
        k = normalize_arabic(word)
        if k.isascii():
            if re.search(rf"(?<![a-z]){re.escape(k)}(?![a-z])", w):
                return True
        elif k in w:
            return True
    return False


def _context_ok(text: str, start: int, end: int, raw: str) -> bool:
    """Reject codes and amounts; demand a contact word for unprefixed 600/800 numbers."""
    if (start >= 2 and text[start - 1] in ".," and text[start - 2].isdigit()) or (
        end + 1 < len(text) and text[end] in ".," and text[end + 1].isdigit()
    ):
        return False  # part of a decimal or thousands-separated amount
    if _has_word(text[max(0, start - _NOT_BEFORE) : start], _NOT_PHONE_WORDS) or _has_word(
        text[end : end + _NOT_AFTER], _NOT_PHONE_WORDS
    ):
        return False
    if re.sub(r"\D", "", raw).startswith(("800", "600")) and not raw.lstrip().startswith("+"):
        if not _BARE_STYLE.match(raw) or "." in raw:
            return False
        near = text[max(0, start - _CONTACT_BEFORE) : start] + " " + text[end : end + _CONTACT_AFTER]
        return _has_word(near, _CONTACT_WORDS)
    return True


def extract_numbers(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Distinct UAE phone numbers in ``text`` as (E.164, span), in order, at most ``MAX_NUMBERS``.

    A run like "600 54 0000 600 54 0044" holds two numbers: inside each run the longest group sequence that
    normalises is taken first, then the scan continues after it. ``to_e164`` only normalises; this function also
    decides whether the run is presented as a phone number (``_context_ok``)."""
    cleaned = ascii_digits(text)  # same length as text: spans stay valid
    out: list[tuple[str, tuple[int, int]]] = []
    seen: set[str] = set()
    for m in _RUN.finditer(cleaned):
        groups = list(_GROUP.finditer(m.group(0)))
        i = 0
        while i < len(groups):
            hit = None
            for j in range(min(len(groups), i + 13), i, -1):
                start, end = groups[i].start(), groups[j - 1].end()
                raw = m.group(0)[start:end]
                e = to_e164(raw)
                if e is not None:
                    hit = (e, (m.start() + start, m.start() + end), j, raw)
                    break
            if hit is None:
                i += 1
                continue
            e164, span, i, raw = hit
            if e164 in seen or not _context_ok(cleaned, span[0], span[1], raw):
                continue
            seen.add(e164)
            out.append((e164, span))
            if len(out) >= MAX_NUMBERS:
                return out
    return out


def mask_number(e164: str) -> str:
    """Masked form for evidence: country code and service prefix (800/600, 5x, area code), then bullets and at most
    the last two digits, so that at least half of the subscriber digits are always hidden ("+971 800•••••67")."""
    if not e164.startswith("+971") or len(e164) < 10:
        return "+971 •••"
    nat = e164[4:]
    plen = 3 if nat.startswith(("800", "600")) else 2 if nat.startswith("5") else 1
    prefix, sub = nat[:plen], nat[plen:]
    tail = min(2, len(sub) // 2)
    return f"+971 {prefix}{'•' * (len(sub) - tail)}{sub[len(sub) - tail :] if tail else ''}"


HMAC_ENV = "FL_EVIDENCE_HMAC_KEY"
_MIN_KEY = 32


def number_id(e164: str, key: str | None = None) -> str | None:
    """Stable correlation id: HMAC-SHA256 of the E.164 number keyed with ``FL_EVIDENCE_HMAC_KEY``.

    Never a bare hash (a UAE number space is small enough to reverse one). Returns None when no key of at least
    32 characters is configured, so the evidence then carries the masked form only."""
    k = key if key is not None else os.environ.get(HMAC_ENV, "")
    if len(k) < _MIN_KEY:
        return None
    return "hm_" + hmac.new(k.encode("utf-8"), e164.encode("ascii"), hashlib.sha256).hexdigest()[:32]


def _https(url: str) -> bool:
    return url.startswith("https://") and len(url) > len("https://") + 3


def parse_contacts(brand_id: str, raw: Any) -> tuple[OfficialContact, ...]:
    """Validate ``official_contacts`` of one brand entry. Raises ValueError on any incomplete or malformed entry."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{brand_id}: official_contacts must be a list")
    out: list[OfficialContact] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"{brand_id}: official_contacts[{i}] must be a mapping")
        kind = str(item.get("kind", ""))
        value = str(item.get("value", "")).strip()
        src = str(item.get("source_url", "") or "")
        ret = str(item.get("retrieved_at", "") or "")
        where = f"{brand_id}: official_contacts[{i}]"
        if kind == "phone":
            if not E164_UAE.match(value) or to_e164(value) != value:
                raise ValueError(f"{where}: phone value must be a UAE number in E.164")
        elif kind == "short_code":
            if not SHORT_CODE.match(value):
                raise ValueError(f"{where}: short_code value must be 3-5 digits")
        else:
            raise ValueError(f"{where}: kind must be phone or short_code")
        if not _https(src):
            raise ValueError(f"{where}: source_url (https) is required")
        if not _DATE.match(ret):
            raise ValueError(f"{where}: retrieved_at (YYYY-MM-DD) is required")
        out.append(
            OfficialContact(
                kind=kind,
                value=value,
                local=str(item.get("local", "")),
                label_en=str(item.get("label_en", "")),
                label_ar=str(item.get("label_ar", "")),
                source_url=src,
                retrieved_at=ret,
            )
        )
    return tuple(out)


def phone_values(contacts: tuple[OfficialContact, ...]) -> Iterator[str]:
    return (c.value for c in contacts if c.kind == "phone")
