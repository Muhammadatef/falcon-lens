"""Flat view of a render for the cascade's ``SandboxFeatures`` (falcon_core.cascade.models).

The cascade reads these top-level keys and ignores the rest; the rich per-profile detail lives under
``profiles``. Everything here is derived data, never raw HTML.
"""

from __future__ import annotations

from typing import Any

from falcon_core.signals.page.features import ProfileFeatures, RenderFeatures

#: Canonical descriptor strings the cascade's keyword classifier recognises, one per field kind.
CASCADE_FIELD = {
    "password": "password",
    "card": "card number",
    "cvv": "cvv",
    "otp": "otp",
    "emirates_id": "emirates id",
    "uae_pass": "uae pass",
}


def primary_profile(f: RenderFeatures) -> ProfileFeatures | None:
    """The profile that best represents the page: one with a credential form, else any loaded."""
    loaded = [p for p in f.profiles.values() if p.final_url and not p.error]
    if not loaded:
        return next(iter(f.profiles.values()), None)
    loaded.sort(key=lambda p: (not any(x.cred_form for x in p.forms), p.profile != "mobile_ar"))
    return loaded[0]


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for i in items:
        key = (str(i.get("origin")), str(i.get("category")))
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def to_flat(f: RenderFeatures, verdict_id: str | None = None) -> dict[str, Any]:
    p = primary_profile(f)
    out: dict[str, Any] = {"verdict_id": verdict_id}
    if p is not None:
        exfil = [{"origin": t.origin, "category": t.exfil_category} for t in p.script_post_targets if t.exfil]
        exfil += [
            {"origin": fm.action_origin, "category": fm.action_exfil_category}
            for fm in p.forms
            if fm.action_exfil and fm.action_origin
        ]
        out.update(
            redirect_chain=[h.url for h in p.redirect_chain],
            final_url=p.final_url,
            title=p.title,
            forms=[
                {
                    "fields": [CASCADE_FIELD[k] for k in fm.sensitive_kinds if k in CASCADE_FIELD],
                    "action_origin": fm.action_origin,
                }
                for fm in p.forms
            ],
            # origins only: a phisher's bot token in the path is never copied into our data
            post_targets=sorted({t.origin for t in p.script_post_targets if t.carries_form_data}),
            # origins that count ONLY because the page has a credential input (no payload/relay evidence)
            credential_rule_origins=sorted(
                {t.origin for t in p.script_post_targets if t.basis == "credential_page_rule"}
                - {t.origin for t in p.script_post_targets if t.basis in ("payload", "relay")}
            ),
            # POSTs with no form-field data (analytics, pixels, keep-alives): informational only
            beacon_origins=sorted(
                {t.origin for t in p.script_post_targets if not t.carries_form_data and t.cross_origin}
            )[:10],
            exfil_targets=_dedupe(exfil),
            hotlinked_origins=p.asset_origins,
            visible_text=p.visible_text,
            favicon_sha256=p.favicon.sha256,
            favicon_phash=p.favicon.phash,
            screenshot_phash=p.screenshot_phash,
            dom_simhash=p.dom_simhash,
            error=p.error,
            truncated=p.network.truncated,
            partial=p.network.partial,
            static_fallback=p.network.static_fallback,
        )
    c = f.cloaking
    out["cloaking"] = {
        "detected": c.diff,
        "diff": c.diff,
        "simhash_distance": c.simhash_distance,
        "inconclusive": c.inconclusive,
        "reasons": c.reasons,
    }
    out["profiles"] = {k: v.model_dump(mode="json") for k, v in f.profiles.items()}
    out["elapsed_ms"] = f.elapsed_ms
    return out
