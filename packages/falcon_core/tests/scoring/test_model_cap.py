"""Fitted classifier alone never produces `dangerous` (L1 D2) and a message is at least its worst link (D1)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from falcon_core.scoring import ArbiterContext, score
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import load_params

from scoring_helpers import make_evidence as mk

DRAFT = load_params(Path(__file__).with_name("params_draft.yaml"))  # no model_cap section: fallback mode
FITTED = dataclasses.replace(DRAFT, model_only_margin=1.0, strong_evidence_adj=1.5)
CRED = ("page.cred_form", {"fields": ["password"]})


def ctx(params):  # type: ignore[no-untyped-def]
    return ArbiterContext(params=params)


def test_fallback_model_alone_is_held_at_suspicious() -> None:
    res = score_with_model([], 0.99, ctx(DRAFT))
    assert res.verdict == "suspicious" and res.calibrated_probability < DRAFT.tau_high


def test_fallback_model_plus_page_risk_evidence_reaches_dangerous() -> None:
    """No new constants: p >= tau_high AND any page/domain risk evidence -> dangerous."""
    res = score_with_model([mk(*CRED)], 0.99, ctx(DRAFT))
    assert res.verdict == "dangerous"


def test_fallback_untrusted_corroboration_does_not_count() -> None:
    llm = mk("brand.claimed_not_owned", {"brand_id": "falcon_demo_bank"}, source="llm:extractor")
    assert score_with_model([llm], 0.99, ctx(DRAFT)).verdict == "suspicious"


def test_fitted_mode_needs_strong_corroboration() -> None:
    assert score_with_model([mk(*CRED)], 0.99, ctx(FITTED)).verdict == "dangerous"  # 1.5 >= strong_adj
    weak = dataclasses.replace(FITTED, strong_evidence_adj=3.0)
    assert score_with_model([mk(*CRED)], 0.99, ctx(weak)).verdict == "suspicious"
    assert score_with_model([], 0.99, ctx(FITTED)).verdict == "suspicious"


def test_hard_rule_floor_is_never_held() -> None:
    feed = mk("rep.openphish", {"match": "url", "feed_age_s": 60}, source="openphish")
    assert score_with_model([feed], 0.01, ctx(FITTED)).verdict == "dangerous"


def test_draft_p_clf_none_is_plain_arbiter() -> None:
    assert score_with_model([mk(*CRED)], None, ctx(DRAFT)).verdict == score([mk(*CRED)], None, ctx(DRAFT)).verdict


def _msg(child: str):  # type: ignore[no-untyped-def]
    e = mk("message.link_verdict", {"verdict": child})
    return score([e], None, ArbiterContext(input_type="message", params=DRAFT))


def test_message_is_at_least_as_severe_as_its_worst_link() -> None:
    assert _msg("dangerous").verdict == "dangerous"
    res = _msg("suspicious")
    assert res.verdict in ("suspicious", "dangerous") and any(r.rule_id == "H5" for r in res.fired_rules)
    assert _msg("no_warning_signs").verdict == "no_warning_signs"
