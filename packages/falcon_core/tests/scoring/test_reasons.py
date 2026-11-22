"""Template reasons, actions, reporting channels, and contract-shape checks."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from scoring_helpers import DEMO_BRAND, Factory

from falcon_core.scoring import (
    ArbiterContext,
    score,
    template_actions,
    template_reasons,
    verdict_core_fields,
)
from falcon_core.scoring.evidence import from_contract, to_contract
from falcon_core.scoring.reasons import (
    ReportingChannels,
    contract_reasons,
    load_reporting_channels,
    parse_reporting_channels,
)

REPO = Path(__file__).resolve().parents[4]
CONTRACTS = REPO / "contracts"


def _h1_case(mk: Factory) -> list:  # type: ignore[type-arg]
    return [
        mk("brand.claimed_not_owned", {"brand_id": DEMO_BRAND}),
        mk("page.cred_form"),
        mk("url.homograph"),
        mk("page.cloaking"),
        mk("url.free_host_or_tunnel"),
        mk("domain.age", {"age_days": 2}),
    ]


def test_reasons_at_most_three_and_cite_existing_ids(mk: Factory) -> None:
    ev = _h1_case(mk)
    res = score(ev, p_clf=0.5)
    ids = {e.id for e in ev}
    for lang in ("ar", "en"):
        reasons = template_reasons(res, lang)
        assert 1 <= len(reasons) <= 3
        for r in reasons:
            assert r.evidence_ids and set(r.evidence_ids) <= ids


def test_hard_rule_reason_first_then_by_abs_weight(mk: Factory) -> None:
    ev = _h1_case(mk)
    res = score(ev, p_clf=0.5)
    keys = [r.key for r in template_reasons(res, "en")]
    assert keys[0] == "hard_rules.H1"
    # Remaining by |w|: homograph 3.0, then cloaking / domain.age 2.5 (stable), free host dropped.
    assert keys[1] == "reasons.url.homograph"
    assert keys[2] in ("reasons.page.cloaking", "reasons.domain.age.new")
    h1 = template_reasons(res, "en")[0]
    assert set(h1.evidence_ids) == {ev[0].id, ev[1].id}


def test_no_warning_signs_uses_trust_reasons_only(mk: Factory) -> None:
    ev = [
        mk("registry.verified_official", True, source="registry", tier="T0"),
        mk("url.free_host_or_tunnel"),
    ]
    res = score(ev, p_clf=0.6)
    assert res.verdict == "no_warning_signs"
    reasons = template_reasons(res, "en")
    assert [r.key for r in reasons] == ["hard_rules.H3"]


def test_risk_verdict_does_not_show_trust_reasons(mk: Factory) -> None:
    ev = [mk("page.cross_origin_post", {"bot": False}), mk("domain.age", 5000)]
    res = score(ev, p_clf=0.6)
    assert res.verdict == "dangerous"
    assert all(r.key != "reasons.domain.age.old" for r in template_reasons(res, "en"))


def test_degraded_override_reason_first(mk: Factory) -> None:
    err = mk("domain.age", None, error="timeout")
    res = score([err], p_clf=0.01)
    reasons = template_reasons(res, "ar")
    assert reasons[0].text == "لم نتمكن من إكمال كل الفحوصات."
    assert reasons[0].evidence_ids == (err.id,)


def test_no_reasons_without_evidence() -> None:
    assert template_reasons(score([], 0.01), "en") == []


def test_contract_reasons_are_bilingual(mk: Factory) -> None:
    res = score(_h1_case(mk), 0.5)
    for r in contract_reasons(res):
        assert r["ar"] and r["en"] and r["generated_by"] == "template"
        assert len(str(r["ar"])) <= 220 and len(str(r["en"])) <= 220


# --- actions / reporting channels --------------------------------------------------------------


def test_caution_always_present_for_no_warning_signs() -> None:
    acts = template_actions("no_warning_signs", ReportingChannels((), None, None))
    assert acts["caution"]["ar"] and acts["caution"]["en"]  # type: ignore[index]
    assert "caution" not in template_actions("dangerous", ReportingChannels((), None, None))


def test_report_uses_config_channels() -> None:
    ch = load_reporting_channels(str(REPO / "config" / "reporting_channels.yaml"))
    assert ch.channels, "repo config has verified channels"
    acts = template_actions("dangerous", ch)
    report = acts["report"]
    assert report["channels"]  # type: ignore[index]
    for c in report["channels"]:  # type: ignore[index]
        assert c["source_url"].startswith("https://")
        dt.date.fromisoformat(c["retrieved_at"])
        assert {"label_ar", "label_en", "value"} <= set(c)


def test_report_generic_fallback_when_unverified() -> None:
    raw = {
        "source_url": None,
        "channels": [{"label_ar": "x", "label_en": "x", "value": "1"}],
        "generic_fallback": {
            "ar": "أبلغ عبر القنوات الرسمية.",
            "en": "Report via official channels.",
        },
    }
    ch = parse_reporting_channels(raw)
    assert ch.channels == ()
    report = template_actions("suspicious", ch)["report"]
    assert report == {
        "ar": "أبلغ عبر القنوات الرسمية.",
        "en": "Report via official channels.",
        "channels": [],
    }


def test_report_builtin_generic_when_config_missing(tmp_path: Path) -> None:
    ch = load_reporting_channels(str(tmp_path / "missing.yaml"))
    report = template_actions("dangerous", ch)["report"]
    assert report["channels"] == [] and report["ar"] and report["en"]  # type: ignore[index]


# --- contract shape -----------------------------------------------------------------------------


def test_evidence_round_trip(mk: Factory) -> None:
    res = score(_h1_case(mk), 0.5)
    for e in res.weighted_evidence:
        assert from_contract(to_contract(e)) == e


def _validator(name: str):  # type: ignore[no-untyped-def]
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    from referencing.jsonschema import DRAFT202012  # type: ignore[import-not-found, unused-ignore]

    schemas = {p.name: json.loads(p.read_text()) for p in CONTRACTS.glob("*.schema.json")}
    resources = []
    for fname, s in schemas.items():
        res = DRAFT202012.create_resource(s)
        resources += [(fname, res), (s["$id"], res)]
    registry = referencing.Registry().with_resources(resources)
    return jsonschema.Draft202012Validator(schemas[name], registry=registry)


@pytest.mark.parametrize("case", ["h1", "official", "degraded"])
def test_core_fields_validate_against_verdict_schema(mk: Factory, case: str) -> None:
    validator = _validator("verdict.schema.json")
    if case == "h1":
        res = score(_h1_case(mk), 0.5)
    elif case == "official":
        res = score([mk("registry.verified_official", True, source="registry", tier="T0")], 0.3)
    else:
        res = score([mk("domain.age", None, error="timeout")], 0.01, ArbiterContext())
    core = verdict_core_fields(
        res, load_reporting_channels(str(REPO / "config" / "reporting_channels.yaml"))
    )
    verdict = {
        "schema_version": "1.0",
        "verdict_id": "vd_01JD0000000000000000000000",
        "input_type": "url",
        "tier_reached": "T2",
        "model_route": "none",
        "final": True,
        "latency_ms": 10,
        "created_at": "2026-11-22T00:00:00Z",
        **core,
    }
    errors = sorted(validator.iter_errors(verdict), key=str)
    assert not errors, [e.message for e in errors]
    ev_validator = _validator("evidence.schema.json")
    for e in core["evidence"]:  # type: ignore[attr-defined]
        assert not list(ev_validator.iter_errors(e))
    if res.verdict == "no_warning_signs":
        assert "caution" in core["actions"]  # type: ignore[operator]
