"""Arbiter pipeline tests against docs/SCORING.md §1-§4."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from scoring_helpers import DEMO_BRAND, Factory

from falcon_core.scoring import (
    ArbiterContext,
    band,
    has_brand_conflict,
    load_params,
    score,
    t1_should_exit,
    t2_should_exit,
)
from falcon_core.scoring.arbiter import logit, sigmoid

P = load_params()


def test_params_are_draft_and_match_scoring_md() -> None:
    assert P.draft is True
    assert (P.tau_high, P.tau_low) == (0.80, 0.35)
    assert P.weights["rep.openphish"] == 6.0
    assert P.weights["url.homograph"] == 3.0
    assert P.weights["url.typosquat"] == 2.5
    assert P.weights["brand.claimed_not_owned"] == 3.0
    assert P.weights["registry.verified_official"] == -4.0
    assert P.weights["injection.instruction_like_text"] == 1.5
    assert (P.domain_age_lt7, P.domain_age_lt30, P.domain_age_gt3650) == (2.5, 1.5, -1.0)
    assert P.cert_age_lt7 == 0.8
    assert (P.message_rule_weight, P.message_rule_cap) == (0.6, 3.0)
    assert P.h1_p_floor == 0.95
    assert P.h2_max_feed_age_s == 6 * 3600
    assert P.logit_clip == 8.0


# --- bands -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (0.0, "no_warning_signs"),
        (0.3499, "no_warning_signs"),
        (0.35, "suspicious"),
        (0.7999, "suspicious"),
        (0.80, "dangerous"),
        (1.0, "dangerous"),
    ],
)
def test_band_edges(p: float, expected: str) -> None:
    assert band(p, P) == expected


@pytest.mark.parametrize(
    ("p", "expected"), [(0.35, "suspicious"), (0.80, "dangerous"), (0.3499, "no_warning_signs")]
)
def test_band_edges_through_score_are_exact(p: float, expected: str) -> None:
    res = score([], p_clf=p)
    assert res.calibrated_probability == p
    assert res.verdict == expected


# --- H3 / H1 vs the classifier -------------------------------------------------------------------


def test_h3_caps_official_domain_even_with_high_classifier_p(mk: Factory) -> None:
    ev = [
        mk("registry.verified_official", {"brand_id": DEMO_BRAND}, source="registry", tier="T0"),
        mk("url.brand_in_subdomain_or_path"),
        mk("page.cred_form"),
        mk("page.hotlinked_brand_assets"),
    ]
    res = score(ev, p_clf=0.999)
    assert res.verdict == "no_warning_signs"
    assert res.calibrated_probability <= P.h3_p_cap
    assert [r.rule_id for r in res.fired_rules] == ["H3"]


def test_h3_does_not_apply_with_open_redirect(mk: Factory) -> None:
    ev = [mk("registry.verified_official", True, source="registry"), mk("url.open_redirect_abuse")]
    res = score(ev, p_clf=0.95)
    assert "H3" not in {r.rule_id for r in res.fired_rules}
    assert res.verdict == "dangerous"
    # The official-registry trust weight must not soften an abused redirector.
    assert {e.signal: e.weight for e in res.weighted_evidence}["registry.verified_official"] == 0.0


def test_registry_trust_ignored_after_feed_hit(mk: Factory) -> None:
    ev = [
        mk("registry.verified_official", True, source="registry"),
        mk("rep.openphish", {"match": "url", "fresh": False}),
    ]
    res = score(ev, p_clf=None)
    assert {e.signal: e.weight for e in res.weighted_evidence}["registry.verified_official"] == 0.0
    assert res.verdict == "dangerous"


def test_h1_beats_low_classifier_p(mk: Factory) -> None:
    ev = [mk("brand.claimed_not_owned", {"brand_id": DEMO_BRAND}), mk("page.cred_form")]
    res = score(ev, p_clf=0.001)
    assert res.verdict == "dangerous"
    assert res.calibrated_probability >= 0.95
    assert "H1" in {r.rule_id for r in res.fired_rules}


def test_h2_beats_low_classifier_p(mk: Factory) -> None:
    res = score([mk("rep.openphish", {"match": "host", "feed_age_s": 30})], p_clf=0.0)
    assert res.verdict == "dangerous"
    assert res.calibrated_probability >= P.tau_high


def test_h6_floor_is_suspicious(mk: Factory) -> None:
    res = score(
        [mk("message.rule.otp_request"), mk("message.rule.authority")],
        p_clf=0.0,
        ctx=ArbiterContext(input_type="message"),
    )
    assert res.verdict == "suspicious"
    assert res.calibrated_probability >= P.tau_low


# --- log-odds arithmetic -------------------------------------------------------------------------


def test_logodds_adjustment_formula(mk: Factory) -> None:
    res = score([mk("page.cloaking", confidence=0.5), mk("page.cred_form")], p_clf=0.2)
    expected = sigmoid(logit(0.2) + 2.5 * 0.5 + 1.5)
    assert math.isclose(res.calibrated_probability, expected, rel_tol=1e-12)
    assert res.risk_score == round(100 * expected)
    weights = {e.signal: e.weight for e in res.weighted_evidence}
    assert weights == {"page.cloaking": 1.25, "page.cred_form": 1.5}


def test_logit_clipped(mk: Factory) -> None:
    many = [mk("page.cross_origin_post", {"bot": False}) for _ in range(10)]
    res = score(many, p_clf=0.99)
    assert math.isclose(res.calibrated_probability, sigmoid(8.0))
    low = score(
        [mk("registry.verified_official", True, source="registry", tier="T0")] * 1, p_clf=1e-9
    )
    assert low.calibrated_probability >= sigmoid(-8.0) - 1e-12


def test_t1_evidence_not_double_counted_when_p_clf_given(mk: Factory) -> None:
    res = score([mk("url.typosquat"), mk("domain.age", {"age_days": 3})], p_clf=0.3)
    assert res.calibrated_probability == 0.3
    assert {e.signal: e.weight for e in res.weighted_evidence} == {
        "url.typosquat": 2.5,
        "domain.age": 2.5,
    }


def test_draft_classifier_used_when_p_clf_none(mk: Factory) -> None:
    res = score([mk("url.typosquat")], p_clf=None)
    assert res.p_clf_draft is True
    assert math.isclose(res.calibrated_probability, sigmoid(P.draft_intercept + 2.5))
    assert res.verdict == "suspicious"
    empty = score([], None)
    assert empty.verdict == "no_warning_signs"


@pytest.mark.parametrize(
    ("age", "weight"),
    [(0, 2.5), (6.9, 2.5), (7, 1.5), (29, 1.5), (30, 0.0), (3650, 0.0), (3651, -1.0)],
)
def test_domain_age_weights(mk: Factory, age: float, weight: float) -> None:
    res = score([mk("domain.age", {"age_days": age})], p_clf=0.5)
    assert res.weighted_evidence[0].weight == weight


def test_old_domain_trust_only_without_other_risk(mk: Factory) -> None:
    res = score([mk("domain.age", 5000), mk("url.free_host_or_tunnel")], p_clf=0.5)
    assert {e.signal: e.weight for e in res.weighted_evidence}["domain.age"] == 0.0


def test_cert_age(mk: Factory) -> None:
    assert score([mk("domain.cert_age", {"age_days": 2})], 0.5).weighted_evidence[0].weight == 0.8
    assert score([mk("domain.cert_age", {"age_days": 7})], 0.5).weighted_evidence[0].weight == 0.0


def test_message_rules_capped_at_three(mk: Factory) -> None:
    names = ["urgency", "secrecy", "payment", "prize", "job", "investment", "delivery_fee", "fine"]
    ev = [mk(f"message.rule.{n}") for n in names]
    res = score(ev, p_clf=0.1, ctx=ArbiterContext(input_type="message"))
    total = sum(e.weight for e in res.weighted_evidence)
    assert math.isclose(total, 3.0)
    assert math.isclose(res.logit_adjustment, 3.0)
    assert all(e.weight <= 0.6 for e in res.weighted_evidence)


def test_unknown_message_rule_has_no_weight(mk: Factory) -> None:
    assert score([mk("message.rule.not_a_rule")], 0.5).weighted_evidence[0].weight == 0.0


def test_family_mismatch_gets_zero_weight(mk: Factory) -> None:
    res = score([mk("page.cross_origin_post", True, family="llm")], p_clf=0.5)
    assert res.weighted_evidence[0].weight == 0.0
    assert res.calibrated_probability == 0.5


def test_llm_family_evidence_never_moves_p(mk: Factory) -> None:
    res = score(
        [
            mk(
                "llm.investigator_opinion",
                {"verdict": "no_warning_signs"},
                source="llm:investigator",
            )
        ],
        0.6,
    )
    assert res.calibrated_probability == 0.6


def test_trust_evidence_from_llm_source_is_ignored(mk: Factory) -> None:
    forged = mk("registry.verified_official", True, source="llm:extractor")
    res = score([forged], p_clf=0.6)
    assert res.weighted_evidence[0].weight == 0.0
    assert res.calibrated_probability == 0.6


def test_errored_evidence_has_no_weight(mk: Factory) -> None:
    res = score([mk("page.cred_form", None, error="timeout")], p_clf=0.5)
    assert res.weighted_evidence[0].weight == 0.0


def test_absent_observation_has_no_weight(mk: Factory) -> None:
    res = score([mk("url.homograph", False), mk("rep.openphish", {"hit": False})], p_clf=0.5)
    assert all(e.weight == 0.0 for e in res.weighted_evidence)


def test_p_clf_out_of_range_rejected() -> None:
    for bad in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            score([], p_clf=bad)


def test_weighted_evidence_keeps_ids_and_order(mk: Factory) -> None:
    ev = [mk("url.typosquat"), mk("page.cred_form"), mk("llm.note", "x", source="llm:responder")]
    res = score(ev, 0.4)
    assert [e.id for e in res.weighted_evidence] == [e.id for e in ev]
    assert [e.polarity for e in res.weighted_evidence] == ["risk", "risk", "neutral"]


# --- degradation --------------------------------------------------------------------------------


def test_degraded_low_p_is_shown_as_suspicious(mk: Factory) -> None:
    ev = [mk("domain.age", None, error="rdap timeout", tier="T1")]
    res = score(ev, p_clf=0.01)
    assert res.degraded is True
    assert res.verdict == "suspicious"
    assert res.band_verdict == "no_warning_signs"
    assert res.degraded_override is True
    assert res.degraded_reasons == ("signal_error:domain.age",)
    assert res.calibrated_probability == 0.01  # the score is not inflated; only the shown verdict


def test_degraded_never_no_warning_signs_even_on_official(mk: Factory) -> None:
    ev = [
        mk("registry.verified_official", True, source="registry", tier="T0"),
        mk("domain.age", None, error="timeout"),
    ]
    res = score(ev, p_clf=0.01)
    assert res.verdict == "suspicious"


def test_degraded_from_context(mk: Factory) -> None:
    res = score([], p_clf=0.01, ctx=ArbiterContext(extra_degraded_reasons=("sandbox_unavailable",)))
    assert res.degraded and res.verdict == "suspicious"


def test_degraded_does_not_lower_dangerous(mk: Factory) -> None:
    res = score([mk("domain.cert_age", None, error="crt.sh down")], p_clf=0.95)
    assert res.degraded and res.verdict == "dangerous" and not res.degraded_override


def test_t2_error_does_not_degrade_by_itself(mk: Factory) -> None:
    res = score([mk("page.cred_form", None, error="render failed")], p_clf=0.01)
    assert res.degraded is False and res.verdict == "no_warning_signs"


# --- cascade exits ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "conflict", "exits"),
    [
        (0.01, False, True),
        (0.99, False, True),
        (0.5, False, False),
        (0.01, True, False),
        (0.99, True, False),
        (P.eps_low, False, False),
        (P.eps_high, False, False),
    ],
)
def test_t1_exit(p: float, conflict: bool, exits: bool) -> None:
    assert t1_should_exit(p, conflict, P) is exits


def test_brand_conflict_detection(mk: Factory) -> None:
    assert has_brand_conflict([mk("url.typosquat")])
    assert not has_brand_conflict([mk("url.typosquat", False), mk("url.raw_ip_host")])


@pytest.mark.parametrize(
    ("p", "exits"), [(0.24, True), (0.25, False), (0.5, False), (0.85, False), (0.86, True)]
)
def test_t2_exit_band(p: float, exits: bool) -> None:
    assert t2_should_exit(score([], p_clf=p), P) is exits


def test_t2_exit_on_hard_rule(mk: Factory) -> None:
    res = score([mk("message.rule.otp_request"), mk("message.rule.authority")], p_clf=0.5)
    assert t2_should_exit(res, P)


def test_params_injection_via_context(mk: Factory) -> None:
    strict = replace(P, tau_high=0.6)
    assert score([], 0.65, ArbiterContext(params=strict)).verdict == "dangerous"
    assert score([], 0.65).verdict == "suspicious"
