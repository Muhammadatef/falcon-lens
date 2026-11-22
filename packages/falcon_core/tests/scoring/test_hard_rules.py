"""Table-driven tests: every hard rule H1-H6 fires on its trigger and stays silent otherwise."""

from __future__ import annotations

from typing import Any

import pytest
from scoring_helpers import DEMO_BRAND, DEMO_LOOKALIKE, DEMO_OFFICIAL, Factory

from falcon_core.scoring import ArbiterContext, score

Spec = tuple[str, Any, dict[str, Any]]

CLAIM: Spec = ("brand.claimed_not_owned", {"brand_id": DEMO_BRAND}, {})
CRED: Spec = ("page.cred_form", {"fields": ["password", "otp"]}, {})
FRESH_FEED: Spec = ("rep.openphish", {"match": "url", "feed_age_s": 600}, {"source": "openphish"})
OFFICIAL: Spec = (
    "registry.verified_official",
    {"brand_id": DEMO_BRAND},
    {"source": "registry", "tier": "T0"},
)
BOT_POST: Spec = ("page.cross_origin_post", {"bot": True, "target_kind": "bot_api"}, {})
OTP: Spec = ("message.rule.otp_request", True, {})
AUTHORITY: Spec = ("message.rule.authority", True, {})


# (case id, rule, evidence specs, input_type, expected fired?)
CASES: list[tuple[str, str, list[Spec], str, bool]] = [
    # H1 brand mismatch (zero-day)
    ("h1_claim_plus_cred_form", "H1", [CLAIM, CRED], "url", True),
    (
        "h1_claim_plus_payment_request",
        "H1",
        [CLAIM, ("message.rule.payment", True, {})],
        "message",
        True,
    ),
    ("h1_claim_without_intent", "H1", [CLAIM], "url", False),
    ("h1_cred_form_without_claim", "H1", [CRED], "url", False),
    (
        "h1_low_confidence_claim",
        "H1",
        [("brand.claimed_not_owned", {"brand_id": DEMO_BRAND}, {"confidence": 0.5}), CRED],
        "url",
        False,
    ),
    (
        "h1_claim_errored",
        "H1",
        [("brand.claimed_not_owned", None, {"error": "timeout"}), CRED],
        "url",
        False,
    ),
    # H2 known bad
    ("h2_fresh_url_hit", "H2", [FRESH_FEED], "url", True),
    (
        "h2_fresh_host_hit_flag",
        "H2",
        [("rep.openphish", {"match": "host", "fresh": True}, {})],
        "url",
        True,
    ),
    (
        "h2_stale_hit",
        "H2",
        [("rep.openphish", {"match": "url", "feed_age_s": 7 * 3600}, {})],
        "url",
        False,
    ),
    (
        "h2_fresh_false",
        "H2",
        [("rep.openphish", {"match": "url", "fresh": False, "feed_age_s": 10}, {})],
        "url",
        False,
    ),
    (
        "h2_domain_only_match",
        "H2",
        [("rep.openphish", {"match": "domain", "feed_age_s": 10}, {})],
        "url",
        False,
    ),
    ("h2_no_freshness_info", "H2", [("rep.openphish", True, {})], "url", False),
    # H3 verified official
    ("h3_official", "H3", [OFFICIAL], "url", True),
    (
        "h3_official_with_open_redirect",
        "H3",
        [OFFICIAL, ("url.open_redirect_abuse", True, {})],
        "url",
        False,
    ),
    (
        "h3_official_with_feed_hit",
        "H3",
        [OFFICIAL, ("rep.openphish", {"match": "url", "feed_age_s": 99999}, {})],
        "url",
        False,
    ),
    ("h3_not_for_messages", "H3", [OFFICIAL], "message", False),
    (
        "h3_forged_by_llm",
        "H3",
        [("registry.verified_official", True, {"source": "llm:extractor"})],
        "url",
        False,
    ),
    (
        "h3_wrong_family",
        "H3",
        [("registry.verified_official", True, {"family": "injection"})],
        "url",
        False,
    ),
    # H4 exfil to bot
    ("h4_bot_post_with_cred_form", "H4", [BOT_POST, CRED], "url", True),
    (
        "h4_bot_post_credentials_flag",
        "H4",
        [("page.cross_origin_post", {"target_kind": "webhook_relay", "credentials": True}, {})],
        "url",
        True,
    ),
    ("h4_bot_post_no_credentials", "H4", [BOT_POST], "url", False),
    (
        "h4_non_bot_cross_origin_post",
        "H4",
        [("page.cross_origin_post", {"bot": False}, {}), CRED],
        "url",
        False,
    ),
    # H5 message with dangerous link
    (
        "h5_dangerous_link",
        "H5",
        [("message.link_verdict", {"verdict": "dangerous"}, {})],
        "message",
        True,
    ),
    ("h5_email_dangerous_link", "H5", [("email.link_verdict", "dangerous", {})], "email", True),
    (
        "h5_suspicious_link",
        "H5",
        [("message.link_verdict", {"verdict": "suspicious"}, {})],
        "message",
        False,
    ),
    # H6 OTP / remote access + impersonation
    ("h6_otp_plus_authority", "H6", [OTP, AUTHORITY], "message", True),
    (
        "h6_remote_access_plus_display_name",
        "H6",
        [("message.rule.remote_access", True, {}), ("email.display_name_impersonation", True, {})],
        "email",
        True,
    ),
    ("h6_otp_without_impersonation", "H6", [OTP], "message", False),
    (
        "h6_authority_without_ask",
        "H6",
        [AUTHORITY, ("message.rule.urgency", True, {})],
        "message",
        False,
    ),
]

EFFECT_FLOOR = {
    "H1": "dangerous",
    "H2": "dangerous",
    "H4": "dangerous",
    "H5": "dangerous",
    "H6": "suspicious",
}
RANK = {"no_warning_signs": 0, "suspicious": 1, "dangerous": 2}


@pytest.mark.parametrize(
    ("case", "rule", "specs", "input_type", "fires"), CASES, ids=[c[0] for c in CASES]
)
def test_hard_rule_table(
    mk: Factory, case: str, rule: str, specs: list[Spec], input_type: str, fires: bool
) -> None:
    evidence = [mk(sig, obs, **kw) for sig, obs, kw in specs]
    # Low classifier probability so any risk verdict must come from the hard rule.
    res = score(evidence, p_clf=0.01, ctx=ArbiterContext(input_type=input_type))  # type: ignore[arg-type]
    fired = {r.rule_id for r in res.fired_rules}
    assert (rule in fired) is fires, (case, fired)
    if fires:
        tagged = {e.id for e in res.weighted_evidence if e.hard_rule == rule}
        rule_obj = next(r for r in res.fired_rules if r.rule_id == rule)
        assert set(rule_obj.evidence_ids) <= {e.id for e in evidence}
        assert tagged, "triggering evidence must carry hard_rule"
        if rule in EFFECT_FLOOR:
            assert RANK[res.verdict] >= RANK[EFFECT_FLOOR[rule]]
        else:
            assert res.verdict == "no_warning_signs"


def test_h1_floor_is_095(mk: Factory) -> None:
    res = score([mk(*CLAIM[:2]), mk(*CRED[:2])], p_clf=0.0001)
    assert res.verdict == "dangerous"
    assert res.calibrated_probability >= 0.95
    assert res.risk_score >= 95


def test_h1_registry_cross_check_blocks_owned_domain(mk: Factory) -> None:
    ctx = ArbiterContext(
        registrable_domain=DEMO_OFFICIAL, verified_domains={DEMO_BRAND: frozenset([DEMO_OFFICIAL])}
    )
    res = score([mk(*CLAIM[:2]), mk(*CRED[:2])], p_clf=0.01, ctx=ctx)
    assert "H1" not in {r.rule_id for r in res.fired_rules}
    ctx2 = ArbiterContext(
        registrable_domain=DEMO_LOOKALIKE, verified_domains={DEMO_BRAND: frozenset([DEMO_OFFICIAL])}
    )
    res2 = score([mk(*CLAIM[:2]), mk(*CRED[:2])], p_clf=0.01, ctx=ctx2)
    assert "H1" in {r.rule_id for r in res2.fired_rules}


def test_h3_registry_cross_check_requires_listed_domain(mk: Factory) -> None:
    verified = {DEMO_BRAND: frozenset([DEMO_OFFICIAL])}
    ok = score(
        [mk(*OFFICIAL[:2], source="registry")],
        0.5,
        ArbiterContext(registrable_domain=DEMO_OFFICIAL, verified_domains=verified),
    )
    assert [r.rule_id for r in ok.fired_rules] == ["H3"]
    bad = score(
        [mk(*OFFICIAL[:2], source="registry")],
        0.5,
        ArbiterContext(registrable_domain=DEMO_LOOKALIKE, verified_domains=verified),
    )
    assert "H3" not in {r.rule_id for r in bad.fired_rules}


def test_h3_overrides_and_reports_suppressed_rules(mk: Factory) -> None:
    res = score([mk(*OFFICIAL[:2], source="registry"), mk(*CLAIM[:2]), mk(*CRED[:2])], p_clf=0.9)
    assert [r.rule_id for r in res.fired_rules] == ["H3"]
    assert [r.rule_id for r in res.suppressed_rules] == ["H1"]
    assert res.verdict == "no_warning_signs"
