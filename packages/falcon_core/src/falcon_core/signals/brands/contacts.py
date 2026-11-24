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
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

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


def extract_numbers(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Distinct UAE numbers in ``text`` as (E.164, span), in order, at most ``MAX_NUMBERS``.

    A run like "600 54 0000 600 54 0044" holds two numbers: inside each run the longest group sequence that
    normalises is taken first, then the scan continues after it."""
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
                e = to_e164(m.group(0)[start:end])
                if e is not None:
                    hit = (e, (m.start() + start, m.start() + end), j)
                    break
            if hit is None:
                i += 1
                continue
            e164, span, i = hit
            if e164 not in seen:
                seen.add(e164)
                out.append((e164, span))
                if len(out) >= MAX_NUMBERS:
                    return out
    return out


def mask_number(e164: str) -> str:
    """Partially masked form for evidence and logs: country code and first digits, then the last two only."""
    return e164[:6] + "***" + e164[-2:] if len(e164) > 8 else e164[:3] + "***"


def number_sha256(e164: str) -> str:
    return hashlib.sha256(e164.encode("ascii")).hexdigest()


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
