"""Pydantic models round-trip against the JSON Schemas in /contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from falcon_core.contracts import Evidence, Incident, PlatformEvent, Verdict

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
ULID = "01JC8Z9Q3M5N7P2R4T6V8W0XYZ"


def _load(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    return data


def _validator(name: str) -> Draft202012Validator:
    # verdict.schema.json refs "evidence.schema.json", resolved relative to its $id.
    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    registry: Registry[Any] = Registry().with_resources(resources)
    return Draft202012Validator(_load(name), registry=registry)


EVIDENCE: dict[str, Any] = {
    "id": "ev_abc12345",
    "signal": "url.homograph",
    "family": "url",
    "observed": {"skeleton_match": True},
    "display": {"ar": "نطاق مشابه", "en": "Lookalike domain"},
    "weight": 12.5,
    "polarity": "risk",
    "source": "computed",
    "tier": "T0",
    "confidence": 0.9,
    "latency_ms": 3,
}

VERDICT: dict[str, Any] = {
    "schema_version": "1.0",
    "verdict_id": f"vd_{ULID}",
    "input_type": "url",
    "canonical_url": "hxxps://falcon-demo-bank[.]test/login",
    "verdict": "suspicious",
    "risk_score": 55,
    "calibrated_probability": 0.55,
    "evidence": [EVIDENCE],
    "reasons": [{"ar": "سبب", "en": "Reason", "evidence_ids": ["ev_abc12345"]}],
    "actions": {
        "now": {"ar": ["لا تدخل بياناتك"], "en": ["Do not enter details"]},
        "if_already_acted": {"ar": ["اتصل بالبنك"], "en": ["Call your bank"]},
        "report": {"ar": "أبلغ", "en": "Report"},
    },
    "tier_reached": "T0",
    "model_route": "none",
    "degraded": False,
    "final": True,
    "source": "fixture",
    "latency_ms": 120,
    "created_at": "2026-11-22T10:00:00Z",
}

EVENT: dict[str, Any] = {
    "schema_version": "1.0",
    "event_id": f"evt_{ULID}",
    "type": "verdict.created",
    "occurred_at": "2026-11-22T10:00:01Z",
    "source": "fixture",
    "verdict_id": f"vd_{ULID}",
    "payload": {"verdict": "suspicious", "risk_score": 55},
}

INCIDENT: dict[str, Any] = {
    "incident_id": f"inc_{ULID}",
    "type": "campaign",
    "severity": "medium",
    "status": "open",
    "rule_ids": ["R-001"],
    "indicators": [
        {
            "kind": "domain",
            "value_defanged": "falcon-demo-bank[.]test",
            "first_seen": "2026-11-22T10:00:00Z",
        }
    ],
    "linked_verdicts": [f"vd_{ULID}"],
    "timeline": [{"at": "2026-11-22T10:00:02Z", "what": "opened"}],
    "actions": [
        {
            "action_id": "act_1",
            "tool": "raise_alert",
            "mode": "internal_auto",
            "status": "executed",
            "evidence_ids": ["ev_abc12345"],
        }
    ],
    "source": "fixture",
    "created_at": "2026-11-22T10:00:02Z",
    "updated_at": "2026-11-22T10:00:03Z",
}

CASES: list[tuple[str, type[BaseModel], dict[str, Any]]] = [
    ("evidence", Evidence, EVIDENCE),
    ("verdict", Verdict, VERDICT),
    ("event", PlatformEvent, EVENT),
    ("incident", Incident, INCIDENT),
]


@pytest.mark.parametrize(("name", "model", "sample"), CASES, ids=[c[0] for c in CASES])
def test_sample_valid_against_schema(name: str, model: type[BaseModel], sample: dict[str, Any]) -> None:
    errors = list(_validator(name).iter_errors(sample))
    assert errors == []


@pytest.mark.parametrize(("name", "model", "sample"), CASES, ids=[c[0] for c in CASES])
def test_model_roundtrip(name: str, model: type[BaseModel], sample: dict[str, Any]) -> None:
    parsed = model.model_validate(sample)
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    assert list(_validator(name).iter_errors(dumped)) == []
    assert model.model_validate(dumped) == parsed


def test_schema_rejects_unknown_field_and_model_agrees() -> None:
    bad = {**EVIDENCE, "surprise": 1}
    assert list(_validator("evidence").iter_errors(bad))
    with pytest.raises(ValidationError):
        Evidence.model_validate(bad)


def test_schema_rejects_bad_verdict_id_and_model_agrees() -> None:
    bad = {**VERDICT, "verdict_id": "vd_lowercase"}
    assert list(_validator("verdict").iter_errors(bad))
    with pytest.raises(ValidationError):
        Verdict.model_validate(bad)
