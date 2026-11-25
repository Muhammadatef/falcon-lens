"""H7 (SCORING §3): secret-asking form + deterministic brand claim + domain younger than 30 days -> dangerous.

Fixtures use only the invented brand "Falcon Demo Bank". H7 is shipped off; these tests turn it on explicitly.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from falcon_core.scoring import ArbiterContext, score
from falcon_core.scoring.params import ParamsError, load_params, params_from_mapping

from scoring_helpers import DEMO_BRAND, DEMO_LOOKALIKE, DEMO_OFFICIAL
from scoring_helpers import make_evidence as mk

ON = dataclasses.replace(load_params(), h7_enabled=True)
VERIFIED = {DEMO_BRAND: frozenset([DEMO_OFFICIAL])}


def claim(conf: float = 0.5, source: str = "sandbox") -> Any:
    return mk(
        "brand.claimed_not_owned", {"brand_id": DEMO_BRAND, "claimed_in": ["text"]}, confidence=conf, source=source
    )


def form(kinds: list[str]) -> Any:
    return mk("page.cred_form", {"present": True, "field_kinds": kinds, "forms": 1}, source="sandbox")


def age(days: float | None, error: str | None = None) -> Any:
    obs = None if days is None else {"domain": DEMO_LOOKALIKE, "age_days": days}
    return mk("domain.age_days", obs, source="rdap", error=error)


def run(ev: list[Any], params: Any = ON, reg: str = DEMO_LOOKALIKE) -> Any:
    return score(ev, p_clf=0.01, ctx=ArbiterContext(params=params, registrable_domain=reg, verified_domains=VERIFIED))


def fired(res: Any) -> set[str]:
    return {r.rule_id for r in res.fired_rules}


def test_fires_on_all_three_halves_and_cites_them() -> None:
    ev = [claim(), form(["password"]), age(4)]
    res = run(ev)
    assert "H7" in fired(res)
    assert "H1" not in fired(res)  # claim below theta: H1 does not fire, H7 is the young-domain corroboration
    assert res.verdict == "dangerous"
    rule = next(r for r in res.fired_rules if r.rule_id == "H7")
    assert set(rule.evidence_ids) == {e.id for e in ev}
    assert {e.id for e in res.weighted_evidence if e.hard_rule == "H7"} == {e.id for e in ev}


def test_off_by_default_in_shipped_params() -> None:
    assert load_params().h7_enabled is False
    res = run([claim(), form(["password"]), age(4)], params=load_params())
    assert "H7" not in fired(res)


@pytest.mark.parametrize(
    "ev",
    [
        pytest.param([form(["password"]), age(4)], id="no_claim"),
        pytest.param([claim(), age(4)], id="no_form"),
        pytest.param([claim(), form(["email"]), age(4)], id="form_without_secret_field"),
        pytest.param([claim(), form(["password"])], id="no_age"),
        pytest.param([claim(), form(["password"]), age(30)], id="age_30_is_not_young"),
        pytest.param([claim(), form(["password"]), age(400)], id="old_domain"),
        pytest.param([claim(), form(["password"]), age(None, error="rdap_timeout")], id="age_error_is_not_young"),
        pytest.param([claim(source="llm:extractor"), form(["card"]), age(2)], id="llm_claim_never_counts"),
    ],
)
def test_silent_unless_every_half_holds(ev: list[Any]) -> None:
    assert "H7" not in fired(run(ev))


@pytest.mark.parametrize("kind", ["password", "card", "cvv", "otp", "pin", "emirates_id", "uae_pass"])
def test_every_secret_kind_counts(kind: str) -> None:
    assert "H7" in fired(run([claim(), form([kind]), age(10)]))


def test_owned_domain_never_fires() -> None:
    assert "H7" not in fired(run([claim(), form(["password"]), age(3)], reg=DEMO_OFFICIAL))


def test_h3_overrides_h7() -> None:
    off = mk("registry.verified_official", {"brand_id": DEMO_BRAND}, source="registry", tier="T0")
    res = run([off, claim(), form(["password"]), age(3)], reg=DEMO_OFFICIAL)
    assert fired(res) == {"H3"}


def test_params_flag_must_be_bool() -> None:
    import yaml

    from falcon_core.scoring.params import DEFAULT_PARAMS_PATH

    raw = yaml.safe_load(DEFAULT_PARAMS_PATH.read_text())
    raw["hard_rules"]["h7_enabled"] = "yes"
    with pytest.raises(ParamsError):
        params_from_mapping(raw)
    raw["hard_rules"]["h7_enabled"] = True
    assert params_from_mapping(raw).h7_enabled is True
