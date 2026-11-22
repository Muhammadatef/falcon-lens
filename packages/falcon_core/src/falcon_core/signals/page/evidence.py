"""Sandbox features -> Evidence (page.*, brand.claimed_not_owned, visual.favicon_match_brand).

Signals emit evidence with ``weight=0``: the arbiter assigns weights (docs/SCORING.md). Where a
hard rule's precondition is visible in the features, the evidence carries ``hard_rule`` so the
reasons can cite it (H1 brand mismatch, H4 exfil-to-bot). Absent evidence means "not observed".
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from falcon_core.contracts.evidence import Evidence, EvidenceDisplay

from ..visual.brands import BrandRef
from ..visual.evidence import favicon_match_evidence
from .build import js_obfuscation_indicators
from .features import ProfileFeatures, RenderFeatures
from .hosts import host_of, registrable_domain
from .text import normalize


def _eid(*parts: str) -> str:
    return "ev_" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def _ev(
    signal: str,
    family: Any,
    observed: Any,
    ar: str,
    en: str,
    *,
    key: str = "",
    polarity: Any = "risk",
    hard_rule: str | None = None,
) -> Evidence:
    return Evidence(
        id=_eid(signal, key),
        signal=signal,
        family=family,
        observed=observed,
        display=EvidenceDisplay(ar=ar, en=en),
        weight=0.0,
        polarity=polarity,
        hard_rule=hard_rule,
        source="sandbox",
        tier="T2",
    )


def _loaded(f: RenderFeatures) -> list[ProfileFeatures]:
    return [p for p in f.profiles.values() if p.final_url and not p.error]


def _site(p: ProfileFeatures) -> str:
    return registrable_domain(host_of(p.final_url or ""))


def claimed_brands(p: ProfileFeatures, brands: Sequence[BrandRef]) -> dict[str, list[str]]:
    """brand_id -> evidence sources of the claim ('title', 'text', 'favicon', 'assets')."""
    title = normalize(p.title)
    text = normalize(p.visible_text)
    assets = {registrable_domain(h) for h in p.asset_origins}
    cred = any(f.cred_form for f in p.forms)
    fav = {e.observed["brand_id"] for e in favicon_match_evidence(p, brands)}
    out: dict[str, list[str]] = {}
    for b in brands:
        srcs: list[str] = []
        terms = b.name_terms()
        if any(f" {t} " in title for t in terms):
            srcs.append("title")
        if cred and any(f" {t} " in text for t in terms):
            srcs.append("text")  # body mention only counts next to a credential form
        if b.brand_id in fav:
            srcs.append("favicon")
        if assets & {registrable_domain(d) for d in b.verified_domains}:
            srcs.append("assets")
        if srcs:
            out[b.brand_id] = srcs
    return out


def build_page_evidence(features: RenderFeatures, brands: Sequence[BrandRef] = ()) -> list[Evidence]:
    """All page/visual/brand evidence for one render (both profiles merged)."""
    profiles = _loaded(features)
    if not profiles:
        return []
    out: list[Evidence] = []
    by_id = {b.brand_id: b for b in brands}

    # page.cred_form -----------------------------------------------------------------------
    cred_profiles = [p for p in profiles if any(f.cred_form for f in p.forms)]
    cred_kinds = sorted({k for p in profiles for f in p.forms if f.cred_form for k in f.sensitive_kinds})
    if cred_profiles:
        out.append(
            _ev(
                "page.cred_form",
                "page",
                {"kinds": cred_kinds, "profiles": [p.profile for p in cred_profiles]},
                "الصفحة تطلب بيانات حساسة (كلمة مرور أو بطاقة أو رمز تحقق أو هوية)",
                "Page asks for sensitive details (password, card, one-time code or ID)",
            )
        )

    # page.cross_origin_post -----------------------------------------------------------------
    targets: dict[tuple[str, str, bool], dict[str, Any]] = {}
    for p in profiles:
        site = _site(p)
        for form in p.forms:
            if form.action_origin and form.action_cross_origin:
                t = targets.setdefault(
                    (host_of(form.action_origin), "form", form.action_exfil),
                    {
                        "host": host_of(form.action_origin),
                        "kind": "form",
                        "exfil": form.action_exfil,
                        "category": form.action_exfil_category,
                    },
                )
                t["profiles"] = sorted({*t.get("profiles", []), p.profile})
        for pt in p.script_post_targets:
            if pt.cross_origin and host_of(pt.origin) and registrable_domain(host_of(pt.origin)) != site:
                t = targets.setdefault(
                    (host_of(pt.origin), pt.kind, pt.exfil),
                    {
                        "host": host_of(pt.origin),
                        "kind": pt.kind,
                        "exfil": pt.exfil,
                        "category": pt.exfil_category,
                    },
                )
                t["profiles"] = sorted({*t.get("profiles", []), p.profile})
    if targets:
        exfil = any(t["exfil"] for t in targets.values())
        out.append(
            _ev(
                "page.cross_origin_post",
                "page",
                {"targets": list(targets.values())[:10], "exfil_channel": exfil},
                "الصفحة ترسل بيانات إلى موقع آخر" + (" (بوت أو webhook)" if exfil else ""),
                "Page sends data to a different site" + (" (bot API / webhook)" if exfil else ""),
                hard_rule="H4" if exfil and cred_profiles else None,
            )
        )

    # page.hotlinked_brand_assets ------------------------------------------------------------
    hot: dict[str, set[str]] = {}
    for p in profiles:
        site = _site(p)
        for b in brands:
            owned = {registrable_domain(d) for d in b.verified_domains}
            if site in owned:
                continue
            for h in p.asset_origins:
                if registrable_domain(h) in owned:
                    hot.setdefault(b.brand_id, set()).add(h)
    if hot:
        out.append(
            _ev(
                "page.hotlinked_brand_assets",
                "page",
                {"brands": {k: sorted(v)[:5] for k, v in hot.items()}},
                "الصفحة تحمّل صور أو ملفات مباشرة من موقع جهة رسمية",
                "Page loads images or files directly from an official site",
            )
        )

    # page.cloaking ---------------------------------------------------------------------------
    if features.cloaking.diff:
        out.append(
            _ev(
                "page.cloaking",
                "page",
                {
                    "reasons": features.cloaking.reasons,
                    "simhash_distance": features.cloaking.simhash_distance,
                },
                "الصفحة تعرض محتوى مختلفاً حسب الجهاز واللغة",
                "Page shows different content depending on device and language",
            )
        )

    # page.js_obfuscation ---------------------------------------------------------------------
    inds = sorted({i for p in profiles for i in js_obfuscation_indicators(p.js)})
    if inds:
        out.append(
            _ev(
                "page.js_obfuscation",
                "page",
                {"indicators": inds},
                "الصفحة تستخدم شيفرة مموّهة أو تمنع الفحص",
                "Page uses obfuscated script or blocks inspection",
            )
        )

    # visual.favicon_match_brand --------------------------------------------------------------
    seen_fav: set[str] = set()
    for p in profiles:
        for e in favicon_match_evidence(p, brands):
            if e.id not in seen_fav:
                seen_fav.add(e.id)
                out.append(e)

    # brand.claimed_not_owned -----------------------------------------------------------------
    claims: dict[str, set[str]] = {}
    for p in profiles:
        owned_here = _site(p)
        for brand_id, srcs in claimed_brands(p, brands).items():
            b = by_id[brand_id]
            if owned_here in {registrable_domain(d) for d in b.verified_domains}:
                continue
            claims.setdefault(brand_id, set()).update(srcs)
    for brand_id, claim_srcs in claims.items():
        b = by_id[brand_id]
        out.append(
            _ev(
                "brand.claimed_not_owned",
                "brand",
                {
                    "brand_id": brand_id,
                    "claim_sources": sorted(claim_srcs),
                    "cred_form": bool(cred_profiles),
                },
                f"الصفحة تنتحل اسم {b.name_ar or b.name_en} وهي ليست موقعه الرسمي",
                f"Page claims to be {b.name_en} but is not on its official domain",
                key=brand_id,
                hard_rule="H1" if cred_profiles else None,
            )
        )
    return out
