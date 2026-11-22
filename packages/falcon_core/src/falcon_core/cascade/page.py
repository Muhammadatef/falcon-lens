"""T2 evidence from sandbox features: page.*, visual.*, and the reference-based brand check (H1).

Everything in ``SandboxFeatures`` is attacker-controlled. This module only matches it against the
brand registry and fixed vocabularies, and emits small structured observations (defanged origins,
brand ids, kinds, counts). Page text never leaves this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from falcon_core.cascade.evidence import make_evidence
from falcon_core.cascade.models import SandboxFeatures
from falcon_core.scoring.evidence import Evidence
from falcon_core.signals.brands.registry import GENERIC_EN, Brand, BrandRegistry
from falcon_core.signals.url.canonical import canonicalize
from falcon_core.signals.url.textutil import defang, normalize_arabic

# --- credential-form field kinds ---------------------------------------------------------------

_FIELD_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("password", ("password", "passwd", "passcode", "current-password", "new-password")),
    ("card", ("cc-number", "cardnumber", "card-number", "card_number", "card number", "ccnum")),
    ("cvv", ("cvv", "cvc", "csc", "cc-csc", "security code")),
    ("otp", ("otp", "one-time-code", "verification code", "sms code", "رمز التحقق")),
    ("pin", ("pin",)),
    ("emirates_id", ("emirates id", "emirates-id", "emiratesid", "eid", "الهوية")),
    ("uae_pass", ("uae pass", "uaepass", "uae-pass")),
    ("card_expiry", ("cc-exp", "expiry", "exp-date")),
)
STRONG_KINDS = frozenset(["password", "card", "cvv", "otp", "pin", "emirates_id", "uae_pass"])
_DESCRIPTOR_KEYS = ("type", "name", "id", "autocomplete", "label", "kind", "placeholder")

# --- exfiltration targets (messaging-bot APIs, webhook and form relays) ------------------------

_BOT_HOSTS: dict[str, str] = {
    "api.telegram.org": "bot_api",
    "hooks.slack.com": "webhook",
    "webhook.site": "webhook_relay",
    "pipedream.net": "webhook_relay",
    "requestcatcher.com": "webhook_relay",
    "formspree.io": "form_relay",
    "getform.io": "form_relay",
    "formsubmit.co": "form_relay",
    "script.google.com": "form_relay",
    "submit-form.com": "form_relay",
}
EXFIL_KINDS = frozenset(["bot_api", "messaging_bot", "webhook", "webhook_relay", "form_relay"])
# signals/page/exfil.py categories (sandbox) -> hard_rules.BOT_TARGET_KINDS
SANDBOX_CATEGORY = {"messaging_bot_api": "messaging_bot"}
_WEBHOOK_PATHS: dict[str, str] = {"discord.com": "/api/webhooks", "discordapp.com": "/api/webhooks"}


def field_kind(descriptor: str | Mapping[str, Any]) -> str | None:
    if isinstance(descriptor, Mapping):
        text = " ".join(str(descriptor.get(k, "")) for k in _DESCRIPTOR_KEYS)
    else:
        text = str(descriptor)
    t = text.lower()[:300]
    for kind, needles in _FIELD_KINDS:
        for n in needles:
            if (len(n) <= 3 and re.search(rf"(?<![a-z]){re.escape(n)}(?![a-z])", t)) or (len(n) > 3 and n in t):
                return kind
    return None


def form_kinds(fields: Iterable[str | Mapping[str, Any]]) -> set[str]:
    return {k for f in fields if (k := field_kind(f)) is not None}


def target_kind(url_or_origin: str) -> str | None:
    c = canonicalize(url_or_origin if "://" in url_or_origin else f"https://{url_or_origin}")
    if not c.ok:
        return None
    host = c.host
    for h, kind in _BOT_HOSTS.items():
        if host == h or host.endswith("." + h):
            return kind
    for h, path in _WEBHOOK_PATHS.items():
        if (host == h or host.endswith("." + h)) and c.path.startswith(path):
            return "webhook"
    return None


def _registrable(url_or_origin: str | None) -> str:
    if not url_or_origin:
        return ""
    c = canonicalize(url_or_origin if "://" in url_or_origin else f"https://{url_or_origin}")
    return c.registrable if c.ok else ""


def _origin_defanged(url_or_origin: str) -> str:
    c = canonicalize(url_or_origin if "://" in url_or_origin else f"https://{url_or_origin}")
    if not c.ok:
        return defang(url_or_origin[:100])
    return defang(f"{c.scheme}://{c.host_ascii}")


# --- brand claims ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BrandMatcher:
    """One alternation per script, longest phrase first, so overlapping phrases
    ("falcon demo bank" / "demo bank") count once per mention."""

    brand: Brand
    latin: re.Pattern[str] | None
    acronyms: re.Pattern[str] | None  # case-sensitive (FAB, ADCB), avoids "fab deals"
    arabic: re.Pattern[str] | None  # over normalised Arabic text


def _alternation(phrases: list[str], left: str, right: str, flexible_space: bool) -> re.Pattern[str] | None:
    if not phrases:
        return None
    parts = []
    for p in sorted(set(phrases), key=len, reverse=True):
        e = re.escape(p)
        parts.append(e.replace(r"\ ", r"[\s\-_]+") if flexible_space else e)
    return re.compile(rf"{left}(?:{'|'.join(parts)}){right}")


def _phrases(b: Brand) -> tuple[list[str], list[str], list[str]]:
    base = re.sub(r"\(.*?\)", " ", b.name_en).split(" - ")[0]
    latin = [" ".join(base.lower().split())]
    acronyms = [
        part.strip()
        for m in re.findall(r"\(([^)]*)\)", b.name_en)
        for part in re.split(r"[/,]", m)
        if part.strip().isupper() and len(part.strip()) >= 3
    ]
    for kw in b.keywords_en:
        words = str(kw).lower().split()
        if len(words) >= 2 and not any(w in GENERIC_EN for w in words):
            latin.append(" ".join(words))
    arabic = [normalize_arabic(b.name_ar).strip()] if b.name_ar else []
    for kw in b.keywords_ar:
        k = normalize_arabic(str(kw)).strip()
        if len(k.split()) >= 2 and k not in arabic:
            arabic.append(k)
    latin = [p for p in dict.fromkeys(latin) if len(p) >= 3]
    return latin, acronyms, [a for a in arabic if len(a) >= 3]


def _matchers(reg: BrandRegistry) -> tuple[BrandMatcher, ...]:
    return _matchers_cached(id(reg), reg)


@lru_cache(maxsize=8)
def _matchers_cached(_key: int, reg: BrandRegistry) -> tuple[BrandMatcher, ...]:
    out = []
    for b in reg.brands:
        latin, acr, ar = _phrases(b)
        out.append(
            BrandMatcher(
                brand=b,
                latin=_alternation(latin, r"(?<![a-z0-9])", r"(?![a-z0-9])", True),
                acronyms=_alternation(acr, r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])", False),
                arabic=_alternation(ar, r"(?<!\w)", "", True),
            )
        )
    return tuple(out)


def _count(m: BrandMatcher, text: str) -> int:
    if not text:
        return 0
    n = 0
    if m.latin is not None:
        n += len(m.latin.findall(text.lower()))
    if m.acronyms is not None:
        n += len(m.acronyms.findall(text))
    if m.arabic is not None:
        n += len(m.arabic.findall(normalize_arabic(text)))
    return n


@dataclass(frozen=True, slots=True)
class BrandClaim:
    brand: Brand
    places: tuple[str, ...]  # title | text | favicon
    confidence: float


# Confidence of a claim (assumptions, DECISIONS.md): a title or favicon claim is strong; page text
# needs at least two mentions to reach the H1 threshold (0.70), so a news page that mentions a
# bank once and has a login box does not trigger H1 by itself.
CONF_TITLE = 0.9
CONF_FAVICON = 0.9
CONF_TEXT_REPEATED = 0.75
CONF_TEXT_ONCE = 0.5
CONF_COMBINED = 0.95


def claimed_brands(features: SandboxFeatures, reg: BrandRegistry, favicons: Mapping[str, str]) -> list[BrandClaim]:
    claims: list[BrandClaim] = []
    fav_brand = favicons.get((features.favicon_sha256 or "").lower())
    for m in _matchers(reg):
        places: list[str] = []
        conf = 0.0
        if _count(m, features.title):
            places.append("title")
            conf = max(conf, CONF_TITLE)
        n_text = _count(m, features.visible_text)
        if n_text:
            places.append("text")
            conf = max(conf, CONF_TEXT_REPEATED if n_text >= 2 else CONF_TEXT_ONCE)
        if fav_brand == m.brand.brand_id:
            places.append("favicon")
            conf = max(conf, CONF_FAVICON)
        if len(places) >= 2 and conf >= CONF_TEXT_REPEATED:
            conf = CONF_COMBINED
        if places:
            claims.append(BrandClaim(m.brand, tuple(places), conf))
    claims.sort(key=lambda c: -c.confidence)
    return claims


def owns(brand: Brand, registrable: str) -> bool:
    return bool(registrable) and registrable.lower() in brand.verified_domains


# --- T2 evidence --------------------------------------------------------------------------------


def page_evidence(
    features: SandboxFeatures,
    input_registrable: str,
    reg: BrandRegistry,
    favicons: Mapping[str, str] | None = None,
) -> list[Evidence]:
    """Turn sandbox features into T2 evidence. Pure; never raises on odd input."""
    favicons = favicons or {}
    page_reg = _registrable(features.final_url) or input_registrable
    out: list[Evidence] = []

    # page.cred_form
    cred_forms = []
    all_kinds: set[str] = set()
    for f in features.forms:
        kinds = form_kinds(f.fields)
        if kinds:
            cred_forms.append((f, kinds))
            all_kinds |= kinds
    if cred_forms:
        strong = bool(all_kinds & STRONG_KINDS)
        out.append(
            make_evidence(
                "page.cred_form",
                "page",
                {"present": True, "field_kinds": sorted(all_kinds), "forms": len(cred_forms)},
                tier="T2",
                source="sandbox",
                confidence=1.0 if strong else 0.6,
                en="The page asks for: " + ", ".join(sorted(all_kinds)),
                ar="الصفحة تطلب بيانات حساسة",
            )
        )

    # page.cross_origin_post
    targets: dict[str, dict[str, Any]] = {}
    for f in features.forms:
        if f.action_origin and _registrable(f.action_origin) not in ("", page_reg):
            t = targets.setdefault(f.action_origin, {"credentials": False})
            t["credentials"] = t["credentials"] or bool(form_kinds(f.fields) & STRONG_KINDS)
    for p in features.post_targets:
        if _registrable(p) not in ("", page_reg):
            targets.setdefault(p, {"credentials": False})
    sandbox_kinds: dict[str, str] = {}
    for x in features.exfil_targets:  # sandbox's own exfil classification (origins only)
        origin = x.get("origin")
        if isinstance(origin, str) and origin:
            cat = str(x.get("category") or "")
            cat = SANDBOX_CATEGORY.get(cat, cat)
            sandbox_kinds[origin] = cat if cat in EXFIL_KINDS else "webhook_relay"
            targets.setdefault(origin, {"credentials": False})
    if targets:
        tkinds = {k: target_kind(k) or sandbox_kinds.get(k) for k in targets}
        bot_kind = next((v for v in tkinds.values() if v), None)
        out.append(
            make_evidence(
                "page.cross_origin_post",
                "page",
                {
                    "targets": sorted({_origin_defanged(t) for t in targets})[:5],
                    "bot": bot_kind is not None,
                    "target_kind": bot_kind or "other",
                    "credentials": any(v["credentials"] for v in targets.values()),
                },
                tier="T2",
                source="sandbox",
                en="The page sends form data to another server",
                ar="الصفحة ترسل البيانات إلى خادم آخر",
            )
        )

    # page.hotlinked_brand_assets
    hot: dict[str, list[str]] = {}
    for origin in features.hotlinked_origins:
        r = _registrable(origin)
        b = reg.official_brand(r) if r else None
        if b is not None and not owns(b, page_reg):
            hot.setdefault(b.brand_id, []).append(_origin_defanged(origin))
    for brand_id, origins in sorted(hot.items()):
        out.append(
            make_evidence(
                "page.hotlinked_brand_assets",
                "page",
                {"brand_id": brand_id, "origins": sorted(set(origins))[:5]},
                tier="T2",
                source="sandbox",
                en="The page loads images from a known organisation's site",
                ar="الصفحة تحمّل صورًا من موقع جهة معروفة",
            )
        )

    # page.cloaking
    if features.cloaking.get("detected") is True:
        obs = {str(k)[:40]: v for k, v in list(features.cloaking.items())[:10] if isinstance(v, bool | int | float)}
        out.append(
            make_evidence(
                "page.cloaking",
                "page",
                obs,
                tier="T2",
                source="sandbox",
                en="The page shows different content to different visitors",
                ar="الصفحة تعرض محتوى مختلفًا لزوار مختلفين",
            )
        )

    # visual.favicon_match_brand
    fav_brand_id = favicons.get((features.favicon_sha256 or "").lower())
    if fav_brand_id:
        fb = next((b for b in reg.brands if b.brand_id == fav_brand_id), None)
        if fb is not None and not owns(fb, page_reg):
            out.append(
                make_evidence(
                    "visual.favicon_match_brand",
                    "visual",
                    {"brand_id": fb.brand_id, "match": "sha256"},
                    tier="T2",
                    source="sandbox",
                    en="The page icon matches a known organisation's icon",
                    ar="أيقونة الصفحة تطابق أيقونة جهة معروفة",
                )
            )

    # brand.claimed_not_owned (H1 input)
    for claim in claimed_brands(features, reg, favicons):
        if owns(claim.brand, page_reg) or owns(claim.brand, input_registrable):
            continue
        out.append(
            make_evidence(
                "brand.claimed_not_owned",
                "brand",
                {
                    "brand_id": claim.brand.brand_id,
                    "claimed_in": list(claim.places),
                    "registrable_domain": defang(page_reg) if page_reg else None,
                },
                tier="T2",
                source="sandbox",
                confidence=claim.confidence,
                en=f"The page claims to be {claim.brand.name_en[:80]}, but the site is not theirs",
                ar=f"الصفحة تدّعي أنها {claim.brand.name_ar[:80]} لكن الموقع ليس موقعها",
            )
        )
        break  # strongest claim only: one brand per page
    return out
