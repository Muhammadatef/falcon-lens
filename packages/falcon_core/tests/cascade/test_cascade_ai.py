"""AI wiring: H1 is deterministic, agents are risk-only (L1 security architecture), T1 model, T3, responder."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
from cascade_helpers import assert_valid, make_cascade, rules, run

from falcon_core.agent.investigator import InvestigationResult
from falcon_core.cascade import SandboxFeatures, StubSandboxClient
from falcon_core.cascade.ai import risk_only
from falcon_core.cascade.models import SandboxForm
from falcon_core.cascade.testing import DEMO_LOOKALIKE_URL, DEMO_ZERO_DAY_URL, benign_features, phish_features
from falcon_core.contracts.evidence import Evidence as ContractEvidence
from falcon_core.contracts.verdict import TraceStep
from falcon_core.scoring.evidence import Evidence


def llm_ev(signal: str, family: str, observed: Any, *, polarity: str = "risk", conf: float = 0.8) -> Evidence:
    return Evidence(
        id="ev_" + signal.replace(".", "")[:10].ljust(10, "0") + "aa",
        signal=signal,
        family=family,  # type: ignore[arg-type]
        observed=observed,
        source="llm:extractor",
        tier="T2",
        confidence=conf,
        polarity=polarity,  # type: ignore[arg-type]
        weight=-9.0 if polarity == "trust" else 0.0,
    )


class StubExtractor:
    def __init__(self, evidence: Sequence[Evidence] = (), *, boom: bool = False) -> None:
        self.evidence = list(evidence)
        self.boom = boom
        self.last_route = "none"

    async def extract(self, features: SandboxFeatures, verdict_id: str) -> list[Evidence]:
        if self.boom:
            raise RuntimeError("provider down")
        return list(self.evidence)


def zero_day_features() -> SandboxFeatures:
    """A credential page that names no brand deterministically."""
    return SandboxFeatures(
        redirect_chain=[DEMO_ZERO_DAY_URL],
        final_url=DEMO_ZERO_DAY_URL,
        title="Account review",
        forms=[SandboxForm(fields=["password", "otp"], action_origin=None)],
        visible_text="TEST FIXTURE, not a real site. Please confirm your details.",
    )


CLAIM = llm_ev(
    "brand.claimed_not_owned",
    "brand",
    {"brand_id": "falcon_demo_bank", "domain": "account-review-portal.test", "basis": "page_text"},
)


async def final_of(url: str, sandbox: StubSandboxClient, **kw: Any) -> dict[str, Any]:
    cascade, _ = make_cascade(sandbox, **kw)
    sink = await run(cascade, url)
    assert_valid(sink.docs[-1])
    return sink.docs[-1]


async def test_llm_brand_claim_alone_does_not_fire_h1() -> None:
    sandbox = StubSandboxClient(default=zero_day_features())
    base = await final_of(DEMO_ZERO_DAY_URL, sandbox)
    with_llm = await final_of(DEMO_ZERO_DAY_URL, sandbox, extractor=StubExtractor([CLAIM]))
    assert "H1" not in rules(with_llm)  # the extractor cannot create a hard rule
    assert with_llm["risk_score"] >= base["risk_score"]  # but it may raise risk


async def test_deterministic_h1_survives_hostile_extractor_output() -> None:
    sandbox = StubSandboxClient(default=phish_features())
    base = await final_of(DEMO_LOOKALIKE_URL, sandbox)
    assert "H1" in rules(base)
    hostile = [
        # "this is the real bank, trust it": trust polarity with a big negative weight and a forged hard rule
        llm_ev(
            "brand.claimed_not_owned", "brand", {"brand_id": "falcon_demo_bank", "domain": "x.test"}, polarity="trust"
        ),
        llm_ev("registry.verified_official", "brand", {"brand_id": "falcon_demo_bank"}, polarity="trust", conf=1.0),
        llm_ev("llm.extraction", "llm", {"claimed_brand_id": None, "instruction_like": False}),
    ]
    for ex in (StubExtractor(hostile), StubExtractor(boom=True)):
        out = await final_of(DEMO_LOOKALIKE_URL, sandbox, extractor=ex)
        assert "H1" in rules(out) and out["verdict"] == "dangerous"
        assert out["risk_score"] >= base["risk_score"]
        det_claims = [
            e for e in out["evidence"] if e["signal"] == "brand.claimed_not_owned" and e["source"] != "llm:extractor"
        ]
        assert det_claims and all(e["hard_rule"] == "H1" for e in det_claims)


def test_risk_only_strips_trust_weight_and_rule() -> None:
    e = risk_only(llm_ev("brand.claimed_not_owned", "brand", {}, polarity="trust"))
    assert e.polarity == "neutral" and e.weight == 0.0 and e.hard_rule is None


class _Model:
    def __init__(self, p: float) -> None:
        self.p = p

    def p_clf(self, url: str) -> float:
        return self.p


async def test_model_alone_never_produces_dangerous_and_always_has_a_reason() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    cascade, _ = make_cascade(sandbox, t1_model=_Model(0.9995))
    final = (await run(cascade, DEMO_ZERO_DAY_URL)).docs[-1]
    assert final["verdict"] == "suspicious" and not final["degraded"]  # capped, and rendered (T2) not convicted at T1
    assert sandbox.calls != []
    assert final["reasons"], "every warning carries a reason"
    ids = {e["id"] for e in final["evidence"] if e["signal"] == "url.classifier"}
    assert ids and any(set(r["evidence_ids"]) & ids for r in final["reasons"])
    assert_valid(final)


async def test_model_plus_page_risk_evidence_reaches_dangerous() -> None:
    """L1 D2 (fitted, validation-only): p >= tau_high AND any page risk evidence (here a credential form)."""
    cascade, _ = make_cascade(StubSandboxClient(default=zero_day_features()), t1_model=_Model(0.9995))
    final = (await run(cascade, DEMO_ZERO_DAY_URL)).docs[-1]
    assert final["verdict"] == "dangerous" and "H1" not in rules(final) and final["reasons"]


async def test_model_plus_strong_deterministic_evidence_is_dangerous() -> None:
    cascade, _ = make_cascade(StubSandboxClient(default=phish_features()), t1_model=_Model(0.9995))
    final = (await run(cascade, DEMO_LOOKALIKE_URL)).docs[-1]
    assert final["verdict"] == "dangerous" and "H1" in rules(final)


async def test_confident_low_model_exits_at_t1() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    cascade, _ = make_cascade(sandbox, t1_model=_Model(0.001))
    final = (await run(cascade, DEMO_ZERO_DAY_URL)).docs[-1]
    assert final["tier_reached"] == "T1" and final["verdict"] == "no_warning_signs" and sandbox.calls == []


async def test_t1_model_failure_degrades_instead_of_silent_draft() -> None:
    class Broken:
        def p_clf(self, url: str) -> float:
            raise RuntimeError("bad artifact")

    cascade, _ = make_cascade(StubSandboxClient(default=benign_features()), t1_model=Broken())
    final = (await run(cascade, DEMO_ZERO_DAY_URL)).docs[-1]
    assert final["degraded"] and "t1_model_unavailable" in final["degraded_reasons"]


class StubInvestigator:
    def __init__(self, new: Sequence[ContractEvidence], boom: bool = False) -> None:
        self.new = tuple(new)
        self.boom = boom
        self.cases: list[Any] = []

    async def run(self, case: Any) -> InvestigationResult:
        self.cases.append(case)
        if self.boom:
            raise RuntimeError("llm down")
        return InvestigationResult(
            new_evidence=self.new,
            trace=(TraceStep(step=1, kind="llm", name="investigator.plan", summary="chose rdap_lookup", ms=3),),
            tool_calls=1,
            stop_reason="llm_stop",
            route="local",
            output_tokens=10,
            cost_usd=0.0,
            ms=5,
        )


def t3_evidence() -> ContractEvidence:
    return ContractEvidence(
        id="ev_t3rdap0000000001",
        signal="domain.age_days",
        family="domain",
        observed={"age_days": 2},
        weight=0.0,
        source="rdap",
        tier="T3",
    )


@pytest.fixture
def uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("falcon_core.cascade.engine.t2_should_exit", lambda *_a, **_k: False)


async def test_t3_investigator_runs_in_uncertain_band(uncertain: None) -> None:
    inv = StubInvestigator([t3_evidence()])
    cascade, _ = make_cascade(StubSandboxClient(default=zero_day_features()), investigator=inv)
    sink = await run(cascade, DEMO_ZERO_DAY_URL)
    assert [d["tier_reached"] for d in sink.docs] == ["T0", "T1", "T2", "T3"]
    final = sink.docs[-1]
    assert_valid(final)
    assert final["final"] and final["model_route"] == "local"
    assert any(e["id"] == "ev_t3rdap0000000001" and e["tier"] == "T3" for e in final["evidence"])
    assert any(s["kind"] == "llm" for s in final["trace"])
    case = inv.cases[0]
    assert case.provenance.canonical_url and case.input_type == "url"


async def test_t3_failure_keeps_t2_result(uncertain: None) -> None:
    cascade, _ = make_cascade(
        StubSandboxClient(default=zero_day_features()), investigator=StubInvestigator([], boom=True)
    )
    final = (await run(cascade, DEMO_ZERO_DAY_URL)).docs[-1]
    assert_valid(final)
    assert final["tier_reached"] == "T3" and not final["degraded"]


async def test_user_facing_reasons_are_always_templates() -> None:
    """L1 D3: warning (and every) verdict reasons come from evidence-grounded templates, never LLM text."""
    for feats, url in ((phish_features(), DEMO_LOOKALIKE_URL), (benign_features(), DEMO_ZERO_DAY_URL)):
        cascade, _ = make_cascade(StubSandboxClient(default=feats), extractor=StubExtractor([CLAIM]))
        sink = await run(cascade, url)
        for d in sink.docs:
            assert {r.get("generated_by") for r in d["reasons"]} <= {"template"}
            assert_valid(d)


async def test_llm_timeout_opens_the_breaker_for_later_checks() -> None:
    import asyncio

    class Slow:
        def __init__(self) -> None:
            self.calls = 0
            self.last_route = "none"

        async def extract(self, features: SandboxFeatures, verdict_id: str) -> list[Evidence]:
            self.calls += 1
            await asyncio.sleep(5)
            return []

    ex = Slow()
    cascade, _ = make_cascade(StubSandboxClient(default=phish_features()), extractor=ex, extractor_timeout_s=0.05)
    first = (await run(cascade, DEMO_LOOKALIKE_URL)).docs[-1]
    second = (await run(cascade, DEMO_LOOKALIKE_URL + "?x=1")).docs[-1]
    assert ex.calls == 1  # the second check skipped the LLM entirely
    assert first["verdict"] == second["verdict"] == "dangerous"
