"""Brand registry loaded from data/brands.yaml (verified official domains; see that file for source URLs and dates)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from falcon_core.signals.url.canonical import psl_split
from falcon_core.signals.url.textutil import compact, normalize_arabic

# Words that describe a service or action, not a brand: never a brand token on their own.
GENERIC_EN = frozenset(
    [
        "fine",
        "fines",
        "traffic",
        "violation",
        "violations",
        "case",
        "report",
        "parcel",
        "package",
        "delivery",
        "customs",
        "fee",
        "redelivery",
        "tracking",
        "online",
        "banking",
        "card",
        "blocked",
        "account",
        "verify",
        "verification",
        "bill",
        "recharge",
        "balance",
        "points",
        "rewards",
        "suspended",
        "otp",
        "payment",
        "pay",
        "refund",
        "services",
        "service",
        "renew",
        "renewal",
        "visa",
        "residency",
        "identity",
        "digital",
        "id",
        "login",
        "unpaid",
        "tag",
        "toll",
        "mobile",
        "sim",
        "government",
        "clearance",
        "parking",
        "vehicle",
        "file",
        "disconnection",
        "compliance",
        "sanctions",
        "frozen",
        "kyc",
        "update",
        "electricity",
        "water",
        "gas",
    ]
)
GENERIC_AR = frozenset(
    normalize_arabic(w)
    for w in [
        "مخالفة",
        "مخالفات",
        "بلاغ",
        "قضية",
        "تحقق",
        "حساب",
        "فاتورة",
        "شحن",
        "رصيد",
        "تأشيرة",
        "إقامة",
        "تجديد",
        "جمارك",
        "طرد",
        "شحنة",
        "توصيل",
        "تتبع",
        "سداد",
        "استرداد",
        "فصل",
        "خدمات",
        "مواقف",
        "رسوم",
        "مكافآت",
        "إيقاف",
        "امتثال",
        "مجمد",
        "بطاقة",
        "موقوفة",
        "تحديث",
        "البيانات",
        "أمان",
        "الخدمة",
    ]
)


@dataclass(frozen=True)
class Brand:
    brand_id: str
    name_en: str
    name_ar: str
    category: str
    verified_domains: tuple[str, ...]
    source_url: str
    retrieved_at: str
    keywords_en: tuple[str, ...] = ()
    keywords_ar: tuple[str, ...] = ()
    # (label, suffix) of each verified domain, e.g. ("adpolice", "gov.ae")
    domain_parts: tuple[tuple[str, str], ...] = field(default=(), compare=False)
    # Latin brand tokens (compact, lowercase) and Arabic tokens (normalised, compact)
    tokens_en: tuple[str, ...] = field(default=(), compare=False)
    tokens_ar: tuple[str, ...] = field(default=(), compare=False)

    @property
    def is_demo(self) -> bool:
        return self.category == "demo"


def _short_en(name: str) -> list[str]:
    """Names plus parenthesised acronyms: 'Abu Dhabi Commercial Bank (ADCB)' -> compact name + 'adcb'."""
    out = []
    base = re.sub(r"\(.*?\)", " ", name)
    base = base.split(" - ")[0]
    if c := compact(base):
        out.append(c)
    for m in re.findall(r"\(([^)]*)\)", name):
        for part in re.split(r"[/,]", m):
            if len(c2 := compact(part)) >= 3:
                out.append(c2)
    return out


def _build(entry: dict[str, Any]) -> Brand:
    vd = tuple(str(d).lower() for d in entry.get("verified_domains", []))
    parts = []
    for d in vd:
        _sub, dom, suf, _priv = psl_split(d)
        parts.append((dom, suf))
    toks: list[str] = []
    for label, _suf in parts:
        c = compact(label)
        if c and c not in toks:
            toks.append(c)
    for t in _short_en(entry.get("name_en", "")):
        if t not in toks and len(t) >= 4:
            toks.append(t)
    for kw in entry.get("keywords_en", []):
        words = str(kw).lower().split()
        if len(words) >= 2 and not any(w in GENERIC_EN for w in words):
            t = compact(str(kw))
            if len(t) >= 8 and t not in toks:
                toks.append(t)
    ar: list[str] = []
    for kw in [entry.get("name_ar", ""), *entry.get("keywords_ar", [])]:
        t = compact(str(kw))
        if (
            len(t) >= 3
            and t not in GENERIC_AR
            and t not in ar
            and not all(w in GENERIC_AR for w in _words_ar(str(kw)))
        ):
            ar.append(t)
    return Brand(
        brand_id=entry["brand_id"],
        name_en=entry.get("name_en", ""),
        name_ar=entry.get("name_ar", ""),
        category=entry.get("category", ""),
        verified_domains=vd,
        source_url=str(entry.get("source_url", "")),
        retrieved_at=str(entry.get("retrieved_at", "")),
        keywords_en=tuple(entry.get("keywords_en", [])),
        keywords_ar=tuple(entry.get("keywords_ar", [])),
        domain_parts=tuple(parts),
        tokens_en=tuple(toks),
        tokens_ar=tuple(ar),
    )


def _words_ar(s: str) -> list[str]:
    return [w for w in normalize_arabic(s).split() if w]


class BrandRegistry:
    def __init__(self, brands: list[Brand]) -> None:
        self.brands = brands
        self._official: dict[str, Brand] = {}
        for b in brands:
            for d in b.verified_domains:
                self._official[d] = b

    @classmethod
    def from_file(cls, path: str | Path) -> BrandRegistry:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls([_build(e) for e in data.get("brands", [])])

    @classmethod
    def from_entries(cls, entries: list[dict[str, Any]]) -> BrandRegistry:
        return cls([_build(e) for e in entries])

    def official_brand(self, registrable: str) -> Brand | None:
        """Brand whose verified list contains this registrable domain (eTLD+1 per PSL)."""
        return self._official.get(registrable.lower())

    def is_official(self, registrable: str) -> bool:
        return registrable.lower() in self._official

    def is_official_host(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return any(host == d or host.endswith("." + d) for d in self._official)


def _find_yaml() -> Path:
    env = os.environ.get("FALCON_BRANDS_YAML")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "data" / "brands.yaml"
        if cand.is_file():
            return cand
    raise FileNotFoundError("data/brands.yaml not found (set FALCON_BRANDS_YAML)")


@lru_cache(maxsize=1)
def default_registry() -> BrandRegistry:
    return BrandRegistry.from_file(_find_yaml())
