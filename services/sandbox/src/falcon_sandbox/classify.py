"""Form-field classification (password / card / CVV / OTP / Emirates ID / UAE PASS).

Pure functions over small attribute descriptors extracted by the sandbox. Arabic and English
labels, names, placeholders and ``autocomplete`` tokens are all considered. Entered values are
never looked at (the sandbox never types).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any

from falcon_core.signals.page.text import normalize


class FieldKind(StrEnum):
    PASSWORD = "password"  # noqa: S105
    CARD = "card"
    CVV = "cvv"
    OTP = "otp"
    EMIRATES_ID = "emirates_id"
    UAE_PASS = "uae_pass"  # noqa: S105
    EMAIL = "email"
    PHONE = "phone"
    USERNAME = "username"
    OTHER = "other"


#: Kinds that make a form a credential/payment harvester (page.cred_form).
SENSITIVE_KINDS: frozenset[FieldKind] = frozenset(
    {
        FieldKind.PASSWORD,
        FieldKind.CARD,
        FieldKind.CVV,
        FieldKind.OTP,
        FieldKind.EMIRATES_ID,
        FieldKind.UAE_PASS,
    }
)

#: Controls a visitor cannot type a secret into. Their label text ("One time" / "Monthly" on a donation
#: frequency radio, "PIN this" on a button) must never make a form look like a credential harvester.
NON_TYPEABLE_TYPES: frozenset[str] = frozenset(
    {
        "radio",
        "checkbox",
        "submit",
        "button",
        "reset",
        "image",
        "file",
        "range",
        "color",
        "select",
        "select-one",
        "select-multiple",
        "date",
        "datetime-local",
        "month",
        "week",
        "time",
    }
)

_AUTOCOMPLETE: dict[str, FieldKind] = {
    "cc-number": FieldKind.CARD,
    "cc-exp": FieldKind.CARD,
    "cc-exp-month": FieldKind.CARD,
    "cc-exp-year": FieldKind.CARD,
    "cc-name": FieldKind.CARD,
    "cc-csc": FieldKind.CVV,
    "one-time-code": FieldKind.OTP,
    "current-password": FieldKind.PASSWORD,
    "new-password": FieldKind.PASSWORD,
    "email": FieldKind.EMAIL,
    "tel": FieldKind.PHONE,
    "username": FieldKind.USERNAME,
}


def _phrases(*items: str) -> tuple[str, ...]:
    """Pre-normalise phrases so Arabic spelling variants match."""
    return tuple(normalize(i).strip() for i in items)


# Ordered: first matching rule wins. A phrase matches only as whole word(s).
_STRONG: tuple[tuple[FieldKind, tuple[str, ...]], ...] = (
    (
        FieldKind.UAE_PASS,
        _phrases(
            "uae pass",
            "uaepass",
            "الهوية الرقمية",
            "هوية رقمية",
            "الامارات باس",
            "يو ايه اي باس",
        ),
    ),
    (
        FieldKind.EMIRATES_ID,
        _phrases(
            "emirates id",
            "emiratesid",
            "emirates identity",
            "eid number",
            "eid no",
            "eid",
            "الهوية الاماراتية",
            "هوية الامارات",
            "رقم الهوية",
            "بطاقة الهوية",
            "الهوية الوطنية",
        ),
    ),
    (
        FieldKind.CVV,
        _phrases(
            "cvv",
            "cvv2",
            "cvc",
            "cvc2",
            "csc",
            "security code",
            "card verification",
            "card security",
            "رمز الامان",
            "رمز التحقق من البطاقة",
            "رمز امان البطاقة",
            "الرقم السري للبطاقة",
            "الرمز السري للبطاقة",
        ),
    ),
    (
        FieldKind.CARD,
        _phrases(
            "card number",
            "card no",
            "cardnumber",
            "credit card",
            "debit card",
            "cc number",
            "ccnum",
            "pan",
            "expiry",
            "expiration",
            "exp date",
            "mm yy",
            "mm yyyy",
            "cardholder",
            "card holder",
            "رقم البطاقة",
            "بطاقة الائتمان",
            "بطاقة الخصم",
            "تاريخ الانتهاء",
            "تاريخ انتهاء",
            "صاحب البطاقة",
        ),
    ),
    (
        FieldKind.OTP,
        _phrases(
            "otp",
            "one time",
            "onetime",
            "verification code",
            "sms code",
            "auth code",
            "authentication code",
            "confirmation code",
            "2fa",
            "رمز التحقق",
            "رمز التاكيد",
            "رمز التفعيل",
            "كلمة المرور لمرة واحدة",
            "رمز الرسالة",
            "كود التحقق",
            "رمز مؤقت",
        ),
    ),
    (
        FieldKind.PASSWORD,
        _phrases(
            "password",
            "passwd",
            "pwd",
            "passcode",
            "pin",
            "atm pin",
            "كلمة المرور",
            "كلمة السر",
            "الرقم السري",
            "الرمز السري",
            "كلمة مرور",
        ),
    ),
)

_WEAK: tuple[tuple[FieldKind, tuple[str, ...]], ...] = (
    (FieldKind.EMAIL, _phrases("email", "e mail", "mail", "البريد الالكتروني", "البريد", "ايميل")),
    (
        FieldKind.PHONE,
        _phrases("phone", "mobile", "tel", "telephone", "رقم الجوال", "رقم الهاتف", "الجوال", "هاتف"),
    ),
    (
        FieldKind.USERNAME,
        _phrases("username", "user name", "user id", "login", "اسم المستخدم", "المستخدم"),
    ),
)

_EID_VALUE = re.compile(r"784\s*[-\s]?\s*(?:\d{4}|x{4}|#{4})", re.IGNORECASE)


def _text_blob(desc: Mapping[str, Any]) -> str:
    keys = ("name", "id", "placeholder", "label", "aria")
    return normalize(" ".join(str(desc[k]) for k in keys if desc.get(k)))


def classify_field(desc: Mapping[str, Any]) -> FieldKind:
    """Classify one form control from its attributes."""
    ftype = str(desc.get("type") or "").lower()
    if ftype == "hidden" or ftype in NON_TYPEABLE_TYPES:
        return FieldKind.OTHER
    for token in str(desc.get("autocomplete") or "").lower().split():
        if token in _AUTOCOMPLETE:
            return _AUTOCOMPLETE[token]
    if _EID_VALUE.search(str(desc.get("placeholder") or "")):
        return FieldKind.EMIRATES_ID
    blob = _text_blob(desc)
    for kind, phrases in _STRONG:
        if any(f" {p} " in blob for p in phrases):
            return kind
    if ftype == "password":
        return FieldKind.PASSWORD
    maxlength = int(desc.get("maxlength") or 0)
    mode = str(desc.get("inputmode") or "").lower()
    if ftype in ("text", "tel", "number", "") and mode == "numeric" and maxlength in (4, 5, 6, 8):
        return FieldKind.OTP  # short numeric code box with no better hint
    if ftype == "email":
        return FieldKind.EMAIL
    if ftype == "tel":
        return FieldKind.PHONE
    for kind, phrases in _WEAK:
        if any(f" {p} " in blob for p in phrases):
            return kind
    return FieldKind.OTHER


def classify_fields(descs: Iterable[Mapping[str, Any]]) -> list[FieldKind]:
    return [classify_field(d) for d in descs]


def is_sensitive(kinds: Iterable[FieldKind | str]) -> bool:
    return any(FieldKind(k) in SENSITIVE_KINDS for k in kinds)
