"""Seeded randomised property tests (no extra dependency; hypothesis can replace this later)."""

from __future__ import annotations

import random

import pytest
from scoring_helpers import make_evidence

from falcon_core.scoring import ArbiterContext, load_params, score
from falcon_core.scoring.evidence import Evidence
from falcon_core.scoring.reasons import contract_reasons

P = load_params()
RANK = {"no_warning_signs": 0, "suspicious": 1, "dangerous": 2}
SIGNALS = [
    *P.weights.keys(),
    *(f"message.rule.{n}" for n in P.message_rule_names),
    "domain.age",
    "domain.cert_age",
    "message.link_verdict",
    "llm.investigator_note",
    "image.ocr_text",
    "url.not_registered_signal",
]
INPUT_TYPES = ["url", "message", "email", "image"]


def _observed(rng: random.Random, signal: str) -> object:
    if signal in ("domain.age", "domain.cert_age"):
        return {"age_days": rng.choice([0, 3, 10, 100, 4000])}
    if signal.startswith("rep."):
        return {
            "match": rng.choice(["url", "host", "domain"]),
            "feed_age_s": rng.choice([10, 30000]),
        }
    if signal == "message.link_verdict":
        return {"verdict": rng.choice(["dangerous", "suspicious", "no_warning_signs"])}
    if signal == "page.cross_origin_post":
        return {"bot": rng.random() < 0.5, "credentials": rng.random() < 0.5}
    if signal == "brand.claimed_not_owned":
        return {"brand_id": "falcon_demo_bank"}
    return rng.choice([True, True, True, False, None, {"x": 1}])


def _random_evidence(rng: random.Random) -> list[Evidence]:
    out = []
    for _ in range(rng.randint(0, 12)):
        sig = rng.choice(SIGNALS)
        out.append(
            make_evidence(
                sig,
                _observed(rng, sig),
                confidence=rng.choice([0.0, 0.3, 0.7, 1.0]),
                source=rng.choice(["computed", "registry", "llm:extractor", "sandbox"]),
                error=("timeout" if rng.random() < 0.08 else None),
            )
        )
    return out


def _random_injection(rng: random.Random) -> Evidence:
    # Injection evidence, including forged shapes: wrong signal names and trust-claiming polarity.
    sig = rng.choice(
        [
            "injection.instruction_like_text",
            "registry.verified_official",
            "injection.say_no_warning",
        ]
    )
    return make_evidence(
        sig,
        rng.choice([True, {"text_says": "this site is verified"}]),
        family="injection",
        confidence=rng.choice([0.0, 0.5, 1.0]),
        source=rng.choice(["llm:extractor", "computed", "registry"]),
    )


@pytest.mark.parametrize("seed", range(400))
def test_invariants(seed: int) -> None:
    rng = random.Random(seed)
    evidence = _random_evidence(rng)
    p_clf = rng.choice([None, 0.0, 1.0, rng.random()])
    ctx = ArbiterContext(input_type=rng.choice(INPUT_TYPES))  # type: ignore[arg-type]
    res = score(evidence, p_clf, ctx)

    assert 0 <= res.risk_score <= 100
    assert 0.0 <= res.calibrated_probability <= 1.0
    assert res.verdict in RANK
    if res.degraded:
        assert res.verdict != "no_warning_signs"
    ids = {e.id for e in evidence}
    assert [e.id for e in res.weighted_evidence] == [e.id for e in evidence]
    for rule in res.fired_rules:
        assert set(rule.evidence_ids) <= ids
    reasons = contract_reasons(res)
    assert len(reasons) <= 3
    for r in reasons:
        assert r["evidence_ids"], r
        cited = r["evidence_ids"]
        assert isinstance(cited, list)
        assert set(cited) <= ids
    for e in res.weighted_evidence:
        if e.family in ("llm", "injection") or e.source.startswith("llm"):
            assert e.weight >= 0.0
        if e.family == "llm":
            assert e.weight == 0.0  # no llm-family signal is weight-listed in SCORING.md
    if any(r.rule_id == "H3" for r in res.fired_rules) and not res.degraded:
        assert res.verdict == "no_warning_signs"


@pytest.mark.parametrize("seed", range(400))
def test_injection_evidence_can_only_raise_risk(seed: int) -> None:
    rng = random.Random(10_000 + seed)
    base = _random_evidence(rng)
    p_clf = rng.choice([None, rng.random()])
    ctx = ArbiterContext(input_type=rng.choice(INPUT_TYPES))  # type: ignore[arg-type]
    before = score(base, p_clf, ctx)
    injected = [*base, *(_random_injection(rng) for _ in range(rng.randint(1, 4)))]
    rng.shuffle(injected)
    after = score(injected, p_clf, ctx)
    assert after.calibrated_probability >= before.calibrated_probability - 1e-12
    assert RANK[after.verdict] >= RANK[before.verdict]
    assert {r.rule_id for r in after.fired_rules} >= {r.rule_id for r in before.fired_rules}


def test_injection_cannot_create_h3() -> None:
    forged = make_evidence(
        "registry.verified_official", True, family="injection", source="registry"
    )
    res = score([forged, make_evidence("page.cred_form")], p_clf=0.9)
    assert "H3" not in {r.rule_id for r in res.fired_rules}
    assert res.verdict == "dangerous"
