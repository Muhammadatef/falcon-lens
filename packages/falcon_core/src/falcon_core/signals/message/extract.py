# ruff: noqa: E501
"""Extract URLs (incl. defanged / obfuscated) and UAE phone numbers from message text as child inputs."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_CHILDREN = 20

# Obfuscation undone before matching. Order matters.
_DEOBF: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bh(?:xx|tt)p(s?)\s*(?:\[:\]|\(:\)|:)\s*(?:\[?//\]?|\\\\)", re.I), r"http\1://"),
    (re.compile(r"\bh[x*]{2}p(s?)://", re.I), r"http\1://"),
    (re.compile(r"\s*[\[\(\{]\s*(?:\.|dot|DOT|点)\s*[\]\)\}]\s*"), "."),
    (re.compile(r"\s*[\[\(\{]\s*(?::|colon)\s*[\]\)\}]\s*"), ":"),
    (re.compile(r"\s*[\[\(\{]\s*(?:/|slash)\s*[\]\)\}]\s*"), "/"),
    (re.compile(r"\s*[\[\(\{]\s*(?:at|@)\s*[\]\)\}]\s*", re.I), "@"),
    (re.compile(r"(?<=[a-z0-9-])\s+dot\s+(?=[a-z0-9-])", re.I), "."),
    (re.compile(r"(?<=[a-z0-9-]) \. (?=[a-z0-9-])", re.I), "."),  # "example . test"
    (
        re.compile(
            r"(?<=[a-z0-9-])\.\s(?=(?:test|com|net|org|ae|xyz|top|info|co|me|link|click|online|site|app|cc|ly)\b)",
            re.I,
        ),
        ".",
    ),
)

# TLDs accepted for scheme-less hosts (avoids "e.g", "file.txt").
_BARE_TLDS = [
    "com",
    "net",
    "org",
    "info",
    "biz",
    "ae",
    "xyz",
    "top",
    "icu",
    "click",
    "shop",
    "live",
    "site",
    "online",
    "vip",
    "cfd",
    "sbs",
    "cyou",
    "rest",
    "buzz",
    "monster",
    "work",
    "support",
    "fit",
    "zip",
    "link",
    "life",
    "today",
    "world",
    "bond",
    "co",
    "me",
    "cc",
    "ly",
    "app",
    "io",
    "gov",
    "edu",
    "tk",
    "ml",
    "ga",
    "cf",
    "gq",
    "test",
    "example",
    "page",
    "dev",
    "store",
    "tech",
    "club",
    "pw",
    "ws",
    "to",
    "gl",
    "is",
    "gd",
]
_HOST = r"(?:[a-z0-9¡-￿](?:[a-z0-9¡-￿-]{0,61}[a-z0-9¡-￿])?\.)+"
_URL_RE = re.compile(
    r"(?:(?:https?|ftp)://[^\s<>\"'«»]+)"
    r"|(?:(?<![\w@.-])"
    + _HOST
    + r"(?:"
    + "|".join(_BARE_TLDS)
    + r")(?![a-z0-9-])(?::\d{2,5})?(?:[/?#][^\s<>\"'«»]*)?)",
    re.I,
)
_TRAIL = ".,;:!?)]}>'\"،؛؟…»"
_ARABIC_BLOCK = re.compile(r"[؀-ۿ]")

# Candidate digit runs (with common separators); validated as UAE numbers below.
_PHONE_RE = re.compile(r"(?<![\w+])\+?\d[\d\s().-]{6,20}\d(?![\w])")


@dataclass(frozen=True)
class ChildInput:
    kind: str  # "url" | "phone"
    value: str  # url as found (de-obfuscated) or E.164-ish phone
    span: tuple[int, int] | None = (
        None  # offsets in the cleaned text (urls) / normalised text (phones)
    )
    source: str = "message"


def deobfuscate(text: str) -> str:
    t = text
    for pat, rep in _DEOBF:
        t = pat.sub(rep, t)
    return t


def extract_urls(text: str) -> list[ChildInput]:
    cleaned = _digits_ascii(deobfuscate(text))
    out: list[ChildInput] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(cleaned):
        raw = m.group(0)
        # URLs end where Arabic prose starts glued to them
        am = _ARABIC_BLOCK.search(raw)
        if am:
            raw = raw[: am.start()]
        raw = raw.rstrip(_TRAIL)
        if len(raw) < 4 or "." not in raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(ChildInput("url", raw[:2048], (m.start(), m.start() + len(raw))))
        if len(out) >= MAX_CHILDREN:
            break
    return out


def _digits_ascii(s: str) -> str:
    tbl = {ord(c): str(i) for i, c in enumerate("٠١٢٣٤٥٦٧٨٩")}
    tbl |= {ord(c): str(i) for i, c in enumerate("۰۱۲۳۴۵۶۷۸۹")}
    return s.translate(tbl)


def _uae_national(digits: str) -> str | None:
    """National significant number if ``digits`` is a valid-looking UAE number, else None."""
    if digits.startswith("00971"):
        digits = digits[2:]
    if digits.startswith("971"):
        nat = digits[3:]
        if nat.startswith("0"):
            nat = nat[1:]
    elif digits.startswith("0"):
        nat = digits[1:]
    elif digits.startswith("800"):
        return digits if 6 <= len(digits) <= 9 else None
    else:
        return None
    if nat.startswith("800"):
        return nat if 6 <= len(nat) <= 9 else None
    if nat.startswith("5") and len(nat) == 9:
        return nat
    if nat[:1] in "234679" and len(nat) == 8:
        return nat
    return None


def extract_phones(text: str) -> list[ChildInput]:
    cleaned = _digits_ascii(text)
    out: list[ChildInput] = []
    seen: set[str] = set()
    for m in _PHONE_RE.finditer(cleaned):
        nat = _uae_national(re.sub(r"\D", "", m.group(0)))
        if nat is None:
            continue
        e164 = nat if nat.startswith("800") else "+971" + nat
        if e164 in seen:
            continue
        seen.add(e164)
        out.append(ChildInput("phone", e164, (m.start(), m.end())))
        if len(out) >= MAX_CHILDREN:
            break
    return out


def mask_phone(p: str) -> str:
    return p[:6] + "***" + p[-2:] if len(p) > 8 else p[:3] + "***"
