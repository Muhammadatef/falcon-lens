"""A post flagged ONLY by the credential-page rule may reach `suspicious`, never alone `dangerous` (SCORING §3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from falcon_core.scoring import ArbiterContext, load_params, score

from scoring_helpers import make_evidence as mk

P = load_params(Path(__file__).with_name("params_draft.yaml"))
CTX = ArbiterContext(params=P)
POST_RULE: dict[str, Any] = {
    "targets": ["hxxps://sso[.]example[.]test"],
    "bot": False,
    "target_kind": "other",
    "credentials": False,
    "basis": "credential_page_rule",
}
POST_PAYLOAD: dict[str, Any] = {**POST_RULE, "basis": "payload"}


def _page(post: dict[str, Any]) -> list[Any]:
    return [
        mk("page.cred_form", {"present": True, "field_kinds": ["password"], "forms": 1}),
        mk("page.cross_origin_post", post),
    ]


def _verdict(extra: list[Any], post: dict[str, Any] = POST_RULE, p: float = 0.6) -> str:
    return str(score([*_page(post), *extra], p_clf=p, ctx=CTX).verdict)


def test_rule_only_post_is_capped_at_suspicious_without_lowering_any_weight() -> None:
    assert _verdict([], POST_PAYLOAD) == "dangerous"  # same evidence, payload basis: full weight
    r = score(_page(POST_RULE), p_clf=0.6, ctx=CTX)
    assert r.verdict == "suspicious" and r.calibrated_probability < P.tau_high
    w = {e.signal: e.weight for e in r.weighted_evidence}
    assert w["page.cross_origin_post"] == 3.0 and w["page.cred_form"] == 1.5


def test_corroboration_lifts_the_cap() -> None:
    assert _verdict([mk("domain.age_days", {"age_days": 10})]) == "dangerous"  # young domain
    assert _verdict([mk("url.free_host_or_tunnel", {"suffix": "x.test"})]) == "dangerous"
    assert _verdict([mk("rep.openphish", True)]) == "dangerous"  # feed hit
    assert _verdict([mk("page.cloaking", {"detected": True})]) == "dangerous"
    assert _verdict([mk("brand.claimed_not_owned", {"brand_id": "falcon_demo_bank"})]) == "dangerous"


def test_old_domain_does_not_lift_the_cap() -> None:
    assert _verdict([mk("domain.age_days", {"age_days": 9000})]) == "suspicious"


def test_relay_post_and_h4_stay_dangerous() -> None:
    bot = {**POST_RULE, "bot": True, "target_kind": "messaging_bot", "basis": "payload"}
    assert _verdict([], bot, p=0.2) == "dangerous"
