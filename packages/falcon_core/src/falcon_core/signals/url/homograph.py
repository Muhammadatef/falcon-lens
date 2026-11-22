# ruff: noqa: E501
"""url.homograph: UTS#39 skeleton match against brand domain labels/names, plus mixed-script labels."""

from __future__ import annotations

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.url.canonical import CanonicalURL, _punycode_decode_label
from falcon_core.signals.url.common import T1_TIMEOUT_MS, canon, registry, url_evidence
from falcon_core.signals.url.skeleton import skeleton_ci
from falcon_core.signals.url.textutil import compact
from falcon_core.signals.url.textutil import scripts_in as _scripts_in

SPEC = SignalSpec(
    name="url.homograph",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=("url.homograph",),
)


def _raw_case_label(c: CanonicalURL) -> str:
    """Domain label as typed (case preserved): catches 'paypaI' (capital I) which hosts lowercase to 'paypai'."""
    raw_labels = [
        _punycode_decode_label(x) if x.startswith("xn--") else x for x in c.host_raw_case.split(".")
    ]
    n_suffix = len([x for x in c.suffix.split(".") if x]) if c.suffix else 0
    idx = len(raw_labels) - n_suffix - 1
    return raw_labels[idx] if 0 <= idx < len(raw_labels) else c.domain_label


@signal(SPEC)
def run(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not c.ok or c.is_ip or not c.domain_label:
        return []
    reg = registry(ctx)
    if reg.is_official(c.registrable):
        return []

    candidates = {c.domain_label, _raw_case_label(c), *c.subdomain_labels}
    scripts = _scripts_in(c.domain_label)
    mixed = len(scripts) > 1
    best: tuple[str, str, str, str, str] | None = (
        None  # brand_id, name_en, name_ar, token, candidate
    )
    for cand in candidates:
        cc = compact(cand) if cand.islower() else cand.replace("-", "")
        keys = {skeleton_ci(cand.replace("-", "")), skeleton_ci(cc)}
        plain = {compact(cand), cand.casefold().replace("-", "")}
        for b in reg.brands:
            for tok in b.tokens_en:
                if len(tok) < 4:
                    continue
                if tok in plain:
                    continue  # exact (unconfused) match is not a homograph
                if skeleton_ci(tok) in keys:
                    best = (b.brand_id, b.name_en, b.name_ar, tok, cand)
                    break
            if best:
                break
        if best:
            break

    if best is None and not mixed:
        return []
    reasons: list[str] = []
    if best:
        reasons.append("skeleton_match")
    if mixed:
        reasons.append("mixed_script")
    if not c.domain_label.isascii():
        reasons.append("non_ascii")
    obs: dict[str, object] = {
        "host": c.host_ascii[:200].replace(".", "[.]"),
        "label": c.domain_label[:100],
        "reasons": reasons,
        "scripts": sorted(scripts),
    }
    if best:
        obs.update(brand_id=best[0], matched=best[3], candidate=best[4][:100])
        en = f"Domain imitates {best[1]} with look-alike characters"
        ar = f"النطاق يحاكي اسم «{best[2]}» بأحرف مشابهة"
        return [
            url_evidence(
                "url.homograph",
                obs,
                en,
                ar,
                1.0 if len(reasons) > 1 or "non_ascii" in reasons else 0.9,
            )
        ]
    return [
        url_evidence(
            "url.homograph",
            obs,
            "Domain name mixes different alphabets (possible look-alike)",
            "اسم النطاق يخلط بين أبجديات مختلفة وقد يكون منتحلاً",
            0.6,
        )
    ]
