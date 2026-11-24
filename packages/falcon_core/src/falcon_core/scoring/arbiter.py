"""Deterministic arbiter (docs/SCORING.md). The only component that sets risk_score, p and verdict.

Pipeline (SCORING §1):
1. hard rules first (``hard_rules.evaluate``): floors for H1/H2/H4/H5/H6, cap for H3;
2. classifier probability ``p_clf`` (T1 features). Until T-022 ships a fitted model, ``p_clf=None``
   uses a draft logistic: ``logit = intercept + sum(w_i * c_i)`` over url/domain/reputation
   evidence;
3. ``logit(p) = logit(p_clf) + sum(w_i * c_i)`` over evidence above T1 (page, visual, brand,
   message,
   email, image, injection, llm), clipped to [-clip, clip];
4. final calibrator (identity while draft); ``risk_score = round(100 p)``;
5. bands, then hard-rule floors/cap; a degraded verdict is never ``no_warning_signs``.

Pure functions only: no I/O except loading the packaged params.yaml once.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from falcon_core.scoring import hard_rules
from falcon_core.scoring.evidence import (
    SIGNAL_ALIASES,
    Evidence,
    Polarity,
    canonical_signal,
    confidence_of,
    family_matches,
    is_present,
    observed_get,
    observed_number,
    untrusted_origin,
)
from falcon_core.scoring.hard_rules import FiredRule, InputType
from falcon_core.scoring.params import ScoringParams, load_params

Verdict = Literal["dangerous", "suspicious", "no_warning_signs"]
VERDICT_RANK: dict[str, int] = {"no_warning_signs": 0, "suspicious": 1, "dangerous": 2}

# Families whose evidence feeds the T1 classifier (p_clf) rather than the log-odds adjustment.
CLASSIFIER_FAMILIES: frozenset[str] = frozenset(["url", "domain", "reputation"])
# Signals that indicate the input resembles or claims a brand (blocks a T1 early exit).
BRAND_CONFLICT_SIGNALS: frozenset[str] = frozenset(
    [
        "url.homograph",
        "url.typosquat",
        "url.combosquat",
        "url.brand_in_subdomain_or_path",
        "brand.claimed_not_owned",
        "visual.favicon_match_brand",
    ]
)
# SCORING §2 domain-age rows: older than OLD is the established-domain trust row, younger than YOUNG is risk.
OLD_DOMAIN_DAYS = 3650
YOUNG_DOMAIN_DAYS = 30
DEGRADING_TIERS: frozenset[str] = frozenset(["T0", "T1"])
_P_EPS = 1e-6


@dataclass(frozen=True, slots=True)
class ArbiterContext:
    input_type: InputType = "url"
    registrable_domain: str | None = None
    # brand_id -> registrable verified domains (data/brands.yaml). Optional cross-check for H1/H3.
    verified_domains: Mapping[str, frozenset[str]] | None = None
    # Degradation reported by the cascade itself (e.g. sandbox unreachable), on top of
    # errored evidence.
    extra_degraded_reasons: tuple[str, ...] = ()
    # Signals with criticality "enrichment": their errors are informational, never degrading.
    enrichment_signals: frozenset[str] = frozenset()
    params: ScoringParams | None = None
    # False when the cascade exited before T1 by design (e.g. a T0 feed hit): the missing T1 model is then
    # not a degradation, only a required-but-absent model is.
    t1_required: bool = True


@dataclass(frozen=True, slots=True)
class ArbiterResult:
    risk_score: int
    calibrated_probability: float
    verdict: Verdict
    fired_rules: tuple[FiredRule, ...]
    weighted_evidence: tuple[Evidence, ...]
    degraded: bool
    degraded_reasons: tuple[str, ...] = ()
    suppressed_rules: tuple[FiredRule, ...] = ()
    p_clf: float = 0.0
    p_clf_draft: bool = False  # True when p_clf came from the draft logistic, not a fitted model
    logit_adjustment: float = 0.0
    band_verdict: Verdict = "no_warning_signs"  # verdict from p alone, before the degraded override
    degraded_override: bool = False  # True when a degraded low-p verdict was raised to suspicious
    params_draft: bool = True
    # Evidence that caused degradation (errored T0/T1 signals, invalid input); reasons cite these.
    errored_evidence_ids: tuple[str, ...] = field(default=())


def logit(p: float) -> float:
    p = min(1.0 - _P_EPS, max(_P_EPS, p))
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def band(p: float, params: ScoringParams | None = None) -> Verdict:
    """SCORING §1.5: dangerous if p >= tau_high; suspicious if tau_low <= p < tau_high."""
    prm = params or load_params()
    if p >= prm.tau_high:
        return "dangerous"
    if p >= prm.tau_low:
        return "suspicious"
    return "no_warning_signs"


def _base_weight(ev: Evidence, params: ScoringParams) -> float:
    sig = canonical_signal(ev.signal)
    if sig == "domain.age":
        age = observed_number(ev, "age_days")
        if age is None or age < 0:
            return 0.0
        if age < 7:
            return params.domain_age_lt7
        if age < 30:
            return params.domain_age_lt30
        if age > OLD_DOMAIN_DAYS:
            return params.domain_age_gt3650
        return 0.0
    if sig == "domain.cert_age":
        age = observed_number(ev, "age_days")
        if age is not None and 0 <= age < 7:
            return params.cert_age_lt7
        return 0.0
    if ev.signal.startswith("message.rule."):
        name = ev.signal.removeprefix("message.rule.")
        return params.message_rule_weight if name in params.message_rule_names else 0.0
    if ev.signal == "email.attachment":
        detected = observed_get(ev, "detected_type")
        risky = observed_get(ev, "risky") is True or (
            isinstance(detected, str) and detected in params.attachment_executable_types
        )
        return params.attachment_risky_weight if risky else params.weights.get(ev.signal, 0.0)
    return params.weights.get(ev.signal, 0.0)


def _contributions(evidence: Sequence[Evidence], params: ScoringParams, h3_holds: bool) -> list[float]:
    """Per-evidence contribution ``w_i * c_i`` in log-odds points (same order as ``evidence``).

    ``registry.verified_official`` trust counts only when H3 holds: with open-redirect abuse or
    a feed hit the official domain must not lower the score (the redirect is judged on its
    target).
    """
    contrib: list[float] = []
    for ev in evidence:
        if not is_present(ev) or not family_matches(ev):
            contrib.append(0.0)
            continue
        w = _base_weight(ev, params)
        if w < 0 and untrusted_origin(ev):
            w = 0.0  # LLM, user or injection evidence can only ever raise risk
        if ev.signal == "registry.verified_official" and not h3_holds:
            w = 0.0
        contrib.append(w * confidence_of(ev))

    # One brand mention counts once: several claims for the same brand (e.g. a deterministic one and an
    # extractor one) take the max, never the sum.
    best: dict[str, int] = {}
    for i, ev in enumerate(evidence):
        if ev.signal == "brand.claimed_not_owned" and contrib[i] > 0:
            bid = str(observed_get(ev, "brand_id") or "")
            j = best.get(bid)
            if j is None:
                best[bid] = i
            elif contrib[i] > contrib[j]:
                contrib[j] = 0.0
                best[bid] = i
            else:
                contrib[i] = 0.0

    # message.rule.* : +0.6 each, family total capped at +3.0 (first come, first counted).
    budget = params.message_rule_cap
    for i, ev in enumerate(evidence):
        if ev.signal.startswith("message.rule.") and contrib[i] > 0:
            contrib[i] = min(contrib[i], max(0.0, budget))
            budget -= contrib[i]

    # The same domain fact can arrive twice (T1 signal and T3 tool, or both spellings): count it once, keeping the
    # largest contribution so the result does not depend on evidence order and risk is never hidden by trust.
    groups: dict[str, list[int]] = {}
    for i, ev in enumerate(evidence):
        canon = canonical_signal(ev.signal)
        if canon in SIGNAL_ALIASES.values() and contrib[i] != 0.0:
            groups.setdefault(canon, []).append(i)
    for idxs in groups.values():
        keep = max(idxs, key=lambda k: contrib[k])
        for k in idxs:
            if k != keep:
                contrib[k] = 0.0

    # domain.age > 3650 days is trust only when no other risk evidence fired.
    other_risk = any(c > 0 for c in contrib)
    for i, ev in enumerate(evidence):
        if canonical_signal(ev.signal) == "domain.age" and contrib[i] < 0 and other_risk:
            contrib[i] = 0.0
    return contrib


def _clip(x: float, bound: float) -> float:
    return max(-bound, min(bound, x))


#: Evidence that corroborates a credential-page-rule post (SCORING §3.1): any of these lifts the cap.
_CORROBORATING_SIGNALS = frozenset(
    [
        "brand.claimed_not_owned", "url.free_host_or_tunnel", "page.cloaking",
        "rep.openphish", "rep.gsb", "rep.urlhaus",
        # impersonation signals H1 does not cover
        "url.homograph", "url.typosquat", "url.combosquat", "url.userinfo_trick", "url.bidi_or_zero_width",
        "url.brand_in_subdomain_or_path", "page.hotlinked_brand_assets", "visual.favicon_match_brand",
    ]
)  # fmt: skip
YOUNG_DOMAIN_DAYS = 30


def credential_rule_cap_applies(
    evidence: Sequence[Evidence],
    contrib: Sequence[float],
    fired: Sequence[object],
    p_clf: float | None = None,
    tau_high: float = 1.0,
) -> bool:
    """True when a would-be `dangerous` rests on the credential-page rule alone.

    ``page.cross_origin_post`` with ``basis=credential_page_rule`` means: the page has a password/OTP/card/ID input
    and a script POSTs somewhere else, but nothing shows the form data is in that POST. Such a post may lift a page
    to `suspicious`, never alone to `dangerous`. Corroboration lifts the cap: a fired hard rule (H1/H2/H4/H5/H6),
    brand.claimed_not_owned, a young domain (< 30 days), a free host or tunnel, a feed hit, or detected cloaking.
    No weight is lowered; posts with payload or relay basis are untouched."""
    rule_only = False
    for ev in evidence:
        if (
            ev.signal == "page.cross_origin_post"
            and ev.error is None
            and observed_get(ev, "basis") == "credential_page_rule"
        ):
            rule_only = True
            break
    if not rule_only or fired:
        return False
    if p_clf is not None and p_clf >= tau_high:
        return False  # the fitted T1 model alone is already at `dangerous`: strong independent risk
    for ev, c in zip(evidence, contrib, strict=True):
        if ev.error is not None:
            continue
        if ev.signal in _CORROBORATING_SIGNALS and c > 0:
            return False
        if canonical_signal(ev.signal) == "domain.age":
            age = observed_number(ev, "age_days")
            if age is not None and 0 <= age < YOUNG_DOMAIN_DAYS:
                return False
    return True


def message_text_cap_applies(
    evidence: Sequence[Evidence],
    contrib: Sequence[float],
    fired: Sequence[object],
    p_clf: float | None = None,
    tau_high: float = 1.0,
) -> bool:
    """True when a would-be `dangerous` rests on message wording that includes the fitted ``message.scam_intent``
    and nothing else: no hard rule fired and no positive evidence outside the message family (no link, domain,
    feed or page evidence). Wording alone may lift a message to `suspicious`, never alone to `dangerous`."""
    if fired or (p_clf is not None and p_clf >= tau_high):
        return False
    has_intent = False
    for ev, c in zip(evidence, contrib, strict=True):
        if ev.error is not None or c <= 0:
            continue
        if ev.family != "message":
            return False
        if ev.signal == "message.scam_intent":
            has_intent = True
    return has_intent


def score(
    evidence: Sequence[Evidence],
    p_clf: float | None = None,
    ctx: ArbiterContext | None = None,
) -> ArbiterResult:
    """Score one input. Deterministic and side-effect free."""
    ctx = ctx or ArbiterContext()
    params = ctx.params or load_params()
    evidence = list(evidence)

    # 1. Hard rules over present evidence.
    present = [e for e in evidence if is_present(e)]
    outcome = hard_rules.evaluate(present, params, ctx.input_type, ctx.registrable_domain, ctx.verified_domains)

    # 2-3. Classifier probability plus log-odds adjustment.
    h3_holds = any(r.rule_id == "H3" for r in outcome.fired)
    contrib = _contributions(evidence, params, h3_holds)
    t1_sum = sum(c for e, c in zip(evidence, contrib, strict=True) if e.family in CLASSIFIER_FAMILIES)
    adj = sum(c for e, c in zip(evidence, contrib, strict=True) if e.family not in CLASSIFIER_FAMILIES)

    if p_clf is None:
        draft = True
        base_logit = params.draft_intercept + t1_sum
        p_clf_used = sigmoid(_clip(base_logit, params.logit_clip))
    else:
        if not 0.0 <= p_clf <= 1.0:  # also rejects NaN
            raise ValueError(f"p_clf must be in [0, 1], got {p_clf!r}")
        draft = False
        base_logit = logit(p_clf)
        p_clf_used = p_clf

    if not draft and adj == 0.0 and abs(base_logit) <= params.logit_clip:
        p = p_clf_used  # exact: no round-trip error at band edges
    else:
        p = sigmoid(_clip(base_logit + adj, params.logit_clip))

    # 4. Final calibrator: identity while draft (params rejects other kinds for now).

    # 5. Hard-rule floors, then the H3 cap.
    for rule in outcome.fired:
        if rule.effect == "floor_dangerous":
            p = max(p, params.h1_p_floor if rule.rule_id == "H1" else params.tau_high)
        elif rule.effect == "floor_suspicious":
            p = max(p, params.tau_low)
        elif rule.effect == "cap_no_warning_signs":
            p = min(p, params.h3_p_cap)
    p = min(1.0, max(0.0, p))
    if p >= params.tau_high and credential_rule_cap_applies(evidence, contrib, outcome.fired, p_clf, params.tau_high):
        p = math.nextafter(params.tau_high, 0.0)  # capped at suspicious: see credential_rule_cap_applies
    if p >= params.tau_high and message_text_cap_applies(evidence, contrib, outcome.fired, p_clf, params.tau_high):
        p = math.nextafter(params.tau_high, 0.0)  # capped at suspicious: see message_text_cap_applies
    verdict = band(p, params)

    # Degradation (SCORING §4).
    # Expected configuration states (feed_disabled, rdap_unsupported_tld) are informational.
    errored = [
        e
        for e in evidence
        if e.error is not None
        and e.tier in DEGRADING_TIERS
        and e.error not in params.informational_errors
        and e.signal not in ctx.enrichment_signals
    ]
    invalid = [e for e in present if e.signal in params.degrading_signals and family_matches(e)]
    reasons = tuple(
        dict.fromkeys(
            [f"signal_error:{e.signal}" for e in errored]
            + [f"invalid_input:{e.signal}" for e in invalid]
            + list(ctx.extra_degraded_reasons)
            # No fitted T1 probability for a URL: the draft fallback is used and the verdict is degraded, so by
            # contract invariant 4 it can never be no_warning_signs (SCORING §4).
            + (["t1_model_unavailable"] if p_clf is None and ctx.input_type == "url" and ctx.t1_required else [])
        )
    )
    degraded = bool(reasons)
    band_verdict = verdict
    override = False
    if degraded and verdict == "no_warning_signs":
        verdict = "suspicious"
        override = True

    # Fill Evidence.weight / polarity / hard_rule.
    tags: dict[str, str] = {}
    for rule in outcome.fired:
        for eid in rule.evidence_ids:
            tags.setdefault(eid, rule.rule_id)
    weighted: list[Evidence] = []
    for ev, c in zip(evidence, contrib, strict=True):
        polarity: Polarity = "risk" if c > 0 else "trust" if c < 0 else ev.polarity
        weighted.append(ev.with_scoring(round(c, 4), polarity, tags.get(ev.id, ev.hard_rule)))

    return ArbiterResult(
        risk_score=min(100, max(0, math.floor(100.0 * p + 0.5))),
        calibrated_probability=p,
        verdict=verdict,
        fired_rules=outcome.fired,
        weighted_evidence=tuple(weighted),
        degraded=degraded,
        degraded_reasons=reasons,
        suppressed_rules=outcome.suppressed,
        p_clf=p_clf_used,
        p_clf_draft=draft,
        logit_adjustment=adj,
        band_verdict=band_verdict,
        degraded_override=override,
        params_draft=params.draft,
        errored_evidence_ids=tuple(dict.fromkeys(e.id for e in [*errored, *invalid])),
    )


def has_brand_conflict(evidence: Sequence[Evidence]) -> bool:
    """True when T1 evidence says the input resembles or claims a brand (needs T2 brand check)."""
    return any(e.signal in BRAND_CONFLICT_SIGNALS and family_matches(e) and is_present(e) for e in evidence)


def t1_risk_evidence(result: ArbiterResult, params: ScoringParams | None = None) -> bool:
    """True if T1 saw url/domain/reputation risk: any positive contribution, or a domain-age error.

    A domain younger than 30 days has a positive ``domain.age`` weight; an unknown age (RDAP error that is not a
    configuration state such as ``rdap_unsupported_tld``) counts as risk too (SCORING §1.6).
    """
    prm = params or load_params()
    for e in result.weighted_evidence:
        if e.family in CLASSIFIER_FAMILIES and e.weight > 0:
            return True
        if (
            canonical_signal(e.signal) == "domain.age"
            and e.error is not None
            and e.error not in prm.informational_errors
        ):
            return True
    return False


def t1_should_exit(
    p_clf: float,
    brand_conflict: bool,
    params: ScoringParams | None = None,
    risk_evidence: bool = False,
) -> bool:
    """SCORING §1.6: T1 exits if (p_clf < eps_low or p_clf > eps_high) and no brand conflict.

    The low exit (-> no_warning_signs) is allowed only without url/domain/reputation risk evidence
    (``risk_evidence``); a high exit is not affected.
    """
    prm = params or load_params()
    if brand_conflict:
        return False
    if p_clf > prm.eps_high:
        return True
    return p_clf < prm.eps_low and not risk_evidence


def t2_should_exit(result: ArbiterResult, params: ScoringParams | None = None) -> bool:
    """SCORING §1.6: T2 exits if a hard rule fired or p is outside [tau_low-0.1, tau_high+0.05]."""
    prm = params or load_params()
    if result.fired_rules:
        return True
    p = result.calibrated_probability
    return p < prm.tau_low - prm.t2_margin_low or p > prm.tau_high + prm.t2_margin_high
