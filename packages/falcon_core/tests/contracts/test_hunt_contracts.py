"""Hunt-mode contract additions (docs/design/HUNTER.md section 4): every change round-trips, every addition is optional."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from falcon_core.contracts import HuntCandidate, Incident, Verdict

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
ULID = "01JC8Z9Q3M5N7P2R4T6V8W0XYZ"


def _validator(name: str) -> Draft202012Validator:
    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    registry: Registry[Any] = Registry().with_resources(resources)
    return Draft202012Validator(json.loads((CONTRACTS / f"{name}.schema.json").read_text()), registry=registry)


CANDIDATE: dict[str, Any] = {
    "candidate_id": f"hc_{ULID}",
    "domain_defanged": "falcon-demo-bank-secure[.]test",
    "domain_sha256": "a" * 64,
    "brand_id": "falcon_demo_bank",
    "discovery": "permutation",
    "permutation_kind": "combosquat",
    "reasons": ["permutation:combosquat", "resolves_a"],
    "provenance": {
        "source_id": "fixture",
        "terms_url": None,
        "retrieved_at": "2026-11-24T20:00:00Z",
        "source": "fixture",
    },
    "first_seen": "2026-11-24T20:00:00Z",
    "upstream_seen": None,
    "prescore": 70,
    "status": "confirmed",
    "verdict_id": f"vd_{ULID}",
    "verdict": "dangerous",
    "incident_id": f"inc_{ULID}",
    "time_to_detection_s": 120.0,
    "time_to_detection_basis": "cert_not_before",
}

OLD_INCIDENT: dict[str, Any] = {
    "incident_id": f"inc_{ULID}",
    "type": "campaign",
    "severity": "medium",
    "status": "open",
    "rule_ids": ["R1"],
    "indicators": [
        {"kind": "domain", "value_defanged": "falcon-demo-bank[.]test", "first_seen": "2026-11-22T10:00:00Z"}
    ],
    "linked_verdicts": [f"vd_{ULID}"],
    "timeline": [{"at": "2026-11-22T10:00:02Z", "what": "opened"}],
    "actions": [],
    "source": "fixture",
    "created_at": "2026-11-22T10:00:02Z",
    "updated_at": "2026-11-22T10:00:03Z",
}

OLD_CAMPAIGN: dict[str, Any] = {
    "campaign_id": f"cmp_{ULID}",
    "brand_id": "falcon_demo_bank",
    "title_ar": "حملة",
    "title_en": "Campaign",
    "severity": "high",
    "count": 3,
    "first_seen": "2026-11-22T10:00:00Z",
    "last_seen": "2026-11-22T10:10:00Z",
    "series": [0] * 12,
    "advice_ar": "نصيحة",
    "advice_en": "Advice",
}


def _early_warning() -> dict[str, Any]:
    inc = copy.deepcopy(OLD_INCIDENT)
    inc["type"] = "early_warning"
    inc["rule_ids"] = ["R6"]
    inc["indicators"][0]["found_by"] = "hunt"
    inc["channels"] = ["hunt"]
    inc["detection"] = {
        "origin": "hunt",
        "found_before_report": True,
        "first_hunt_seen": "2026-11-22T10:00:00Z",
        "first_user_seen": None,
    }
    return inc


def test_candidate_valid_and_roundtrips() -> None:
    assert list(_validator("hunt_candidate").iter_errors(CANDIDATE)) == []
    parsed = HuntCandidate.model_validate(CANDIDATE)
    dumped = parsed.model_dump(mode="json")
    assert list(_validator("hunt_candidate").iter_errors(dumped)) == []
    assert HuntCandidate.model_validate(dumped) == parsed


@pytest.mark.parametrize(
    "patch",
    [
        {"domain_defanged": "falcon-demo-bank-secure.test"},  # live name: must be defanged
        {"prescore": 101},
        {"status": "suspected"},
        {"reasons": ["free text"]},
        {"candidate_id": "hc_x"},
        {"surprise": 1},
        {"provenance": {**CANDIDATE["provenance"], "source": "synthetic"}},
    ],
)
def test_candidate_rejects_and_model_agrees(patch: dict[str, Any]) -> None:
    bad = {**CANDIDATE, **patch}
    assert list(_validator("hunt_candidate").iter_errors(bad))
    with pytest.raises(ValidationError):
        HuntCandidate.model_validate(bad)


def test_old_incident_and_campaign_still_valid() -> None:
    assert list(_validator("incident").iter_errors(OLD_INCIDENT)) == []
    Incident.model_validate(OLD_INCIDENT)
    assert list(_validator("campaign").iter_errors(OLD_CAMPAIGN)) == []


def test_early_warning_incident_roundtrips() -> None:
    inc = _early_warning()
    assert list(_validator("incident").iter_errors(inc)) == []
    parsed = Incident.model_validate(inc)
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    dumped["detection"]["first_user_seen"] = None  # nullable but required inside detection
    assert list(_validator("incident").iter_errors(dumped)) == []
    assert Incident.model_validate(dumped) == parsed


def test_incident_detection_is_closed() -> None:
    inc = _early_warning()
    inc["detection"]["extra"] = 1
    assert list(_validator("incident").iter_errors(inc))
    with pytest.raises(ValidationError):
        Incident.model_validate(inc)


def test_campaign_hunt_fields() -> None:
    camp = {**OLD_CAMPAIGN, "found_before_report": True, "hunt_count": 2}
    assert list(_validator("campaign").iter_errors(camp)) == []
    assert list(_validator("campaign").iter_errors({**camp, "hunt_count": -1}))


def test_verdict_channel_hunt() -> None:
    schema = json.loads((CONTRACTS / "verdict.schema.json").read_text())
    assert "hunt" in schema["properties"]["channel"]["enum"]
    assert set(schema["properties"]["source"]["enum"]) == {
        "live",
        "replay",
        "synthetic",
        "fixture",
    }  # truth label untouched
    assert "hunt" in Verdict.model_fields["channel"].annotation.__args__[0].__args__  # type: ignore[union-attr]
