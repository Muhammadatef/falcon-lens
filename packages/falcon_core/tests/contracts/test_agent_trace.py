"""agent_trace.schema.json <-> falcon_core.contracts.agent_trace round-trip."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from falcon_core.contracts.agent_trace import AgentTrace, TraceInterrupt, TraceLlm, TraceRun, TraceStep, TraceTool

SCHEMA: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[4] / "contracts" / "agent_trace.schema.json").read_text()
)
IID = "inc_01M82WG27Z5R018594H571VDK5"

STEP = {
    "seq": 1,
    "node": "propose",
    "started_at": "2026-11-23T00:00:00Z",
    "duration_ms": 4,
    "status": "completed",
    "summary_en": "x",
    "summary_ar": "س",
    "tools": [
        {
            "name": "draft_takedown",
            "mode": "external_draft",
            "status": "ok",
            "evidence_ids": ["rule:R1"],
            "duration_ms": 0,
            "origin": "rule_fallback",
        }
    ],
    "llm": {
        "route": "none",
        "model": "none",
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "repaired": False,
        "fallback_template": True,
    },
    "generated_by": "rule",
    "budget": {"steps_used": 5, "tokens_used": 0, "elapsed_ms": 9},
    "error_code": None,
}
DOC = {
    "incident_id": IID,
    "thread_id": IID,
    "runs": [
        {
            "run_id": "run_1",
            "started_at": "2026-11-23T00:00:00Z",
            "finished_at": None,
            "status": "interrupted",
            "steps": [STEP],
            "interrupt": {
                "action_id": "a",
                "tool": "draft_takedown",
                "waiting_since": "2026-11-23T00:00:01Z",
                "pending_count": 1,
                "decision": None,
                "decided_by": None,
            },
        }
    ],
}


def test_document_validates_against_schema_and_model_and_roundtrips() -> None:
    Draft202012Validator(SCHEMA).validate(DOC)
    model = AgentTrace.model_validate(DOC)
    Draft202012Validator(SCHEMA).validate(json.loads(model.model_dump_json()))
    assert AgentTrace.model_validate_json(model.model_dump_json()) == model


def test_model_fields_match_schema_properties() -> None:
    pairs = [
        (AgentTrace, SCHEMA),
        (TraceRun, SCHEMA["$defs"]["run"]),
        (TraceStep, SCHEMA["$defs"]["step"]),
        (TraceTool, SCHEMA["$defs"]["tool"]),
        (TraceLlm, SCHEMA["$defs"]["step"]["properties"]["llm"]["oneOf"][1]),
        (TraceInterrupt, SCHEMA["$defs"]["run"]["properties"]["interrupt"]["oneOf"][1]),
    ]
    for model, schema in pairs:
        assert set(model.model_fields) == set(schema["properties"]), model.__name__
        required = {n for n, f in model.model_fields.items() if f.is_required()}
        assert required == set(schema["required"]), model.__name__


def test_unknown_fields_are_rejected_by_both() -> None:
    bad = json.loads(json.dumps(DOC))
    bad["runs"][0]["steps"][0]["raw_prompt"] = "leak"
    assert list(Draft202012Validator(SCHEMA).iter_errors(bad))
    with pytest.raises(ValidationError):
        AgentTrace.model_validate(bad)
