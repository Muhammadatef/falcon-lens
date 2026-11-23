from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from graph_helpers import make_env
from jsonschema import Draft202012Validator

from falcon_sentinel.llm import StubLLM
from falcon_sentinel.trace import assemble_trace

SCHEMA = Path(__file__).resolve().parents[3] / "contracts" / "agent_trace.schema.json"
NODES = ["enrich", "compare", "assess", "summarise", "propose", "act"]


class Crash(Exception):
    pass


async def trace_of(env: Any, iid: str) -> dict[str, Any]:
    doc = assemble_trace(iid, await env.repo.trace_list(iid))
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(doc)
    return doc


async def test_planted_campaign_trace_has_six_nodes_and_interrupt():
    env = await make_env()
    iid = env.campaign_id()
    await env.runner().run(iid)
    doc = await trace_of(env, iid)
    assert doc["thread_id"] == iid
    (run,) = doc["runs"]
    assert [s["node"] for s in run["steps"]] == NODES
    assert [s["seq"] for s in run["steps"]] == [1, 2, 3, 4, 5, 6]
    assert run["status"] == "interrupted" and run["steps"][-1]["status"] == "interrupted"
    assert run["interrupt"]["tool"] == "draft_takedown" and run["interrupt"]["decision"] is None
    by = {s["node"]: s for s in run["steps"]}
    assert by["enrich"]["llm"] is None and by["compare"]["llm"] is None
    assert {t["name"] for t in by["enrich"]["tools"]} >= {
        "search_verdicts",
        "find_related_domains",
        "get_past_incidents",
        "feed_status",
    }
    for n in ("assess", "summarise", "propose"):
        llm = by[n]["llm"]
        assert llm["route"] == "local" and llm["tokens_in"] > 0 and llm["fallback_template"] is False
    modes = {t["name"]: t["mode"] for t in by["act"]["tools"]}
    assert modes["block_indicator"] == "internal_auto" and modes["draft_takedown"] == "external_draft"
    blob = json.dumps(doc)
    assert "http://" not in blob and "https://" not in blob and "Return ONLY" not in blob


async def test_template_fallback_is_flagged_and_model_text_never_enters_trace():
    env = await make_env()
    iid = env.campaign_id()
    bad = StubLLM(overrides={"summarise": lambda u: {"en": "see https://evil.example/x", "ar": "x", "claims": []}})
    await env.runner(bad).run(iid)
    doc = await trace_of(env, iid)
    s = {x["node"]: x for x in doc["runs"][0]["steps"]}["summarise"]
    assert s["llm"]["fallback_template"] is True
    assert "evil" not in json.dumps(doc)


async def test_approval_adds_run_and_records_decision():
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner()
    await runner.run(iid)
    (p,) = await runner.pending_approvals(iid)
    await runner.approve(iid, p["action_id"], "op_alice")
    doc = await trace_of(env, iid)
    first, second = doc["runs"]
    assert first["status"] == "interrupted" and first["interrupt"]["decision"] == "approved"
    assert first["interrupt"]["decided_by"] == "op_alice"
    assert second["status"] == "completed" and [s["node"] for s in second["steps"]] == ["act"]
    assert second["steps"][0]["seq"] == 7 and second["steps"][0]["status"] == "completed"


async def test_restart_resume_continues_same_thread_trace():
    from langgraph.checkpoint.memory import InMemorySaver

    env = await make_env()
    iid = env.campaign_id()
    saver = InMemorySaver()
    with pytest.raises(Crash):
        await env.runner(StubLLM(overrides={"propose": lambda u: Crash("died")}), saver).run(iid)
    mid = await trace_of(env, iid)
    assert mid["runs"][0]["status"] == "failed"
    assert mid["runs"][0]["steps"][-1]["status"] == "failed"
    assert mid["runs"][0]["steps"][-1]["error_code"] == "crash"
    await env.runner(StubLLM(), saver).resume_unfinished()  # fresh runner = restarted process
    doc = await trace_of(env, iid)
    assert doc["thread_id"] == iid and len(doc["runs"]) == 2
    resumed = doc["runs"][1]
    assert [s["node"] for s in resumed["steps"]] == ["propose", "act"]  # assess/summarise not redone
    assert resumed["steps"][0]["seq"] == doc["runs"][0]["steps"][-1]["seq"] + 1
    assert resumed["status"] == "interrupted"


def test_stale_running_step_is_failed_once_a_later_run_exists():
    now = datetime.now(UTC)
    step = {
        "node": "enrich",
        "started_at": "2026-01-01T00:00:00Z",
        "duration_ms": 0,
        "status": "running",
        "summary_en": "",
        "summary_ar": "",
        "tools": [],
        "llm": None,
        "budget": {"steps_used": 0, "tokens_used": 0, "elapsed_ms": 0},
        "error_code": None,
    }

    def row(run: str, kind: str, seq: int | None, doc: dict[str, Any]) -> dict[str, Any]:
        return {"incident_id": "i", "thread_id": "i", "run_id": run, "seq": seq, "kind": kind, "at": now, "doc": doc}

    rows = [
        row("a", "run", None, {"phase": "start", "trigger": "start", "decision": None}),
        row("a", "step", 1, step),
        row("b", "run", None, {"phase": "start", "trigger": "resume", "decision": None}),
    ]
    doc = assemble_trace("i", rows)
    assert doc["runs"][0]["status"] == "failed"
    assert doc["runs"][0]["steps"][0]["status"] == "failed"
    assert doc["runs"][0]["steps"][0]["error_code"] == "process_restart"
    assert doc["runs"][1]["status"] == "running"


def test_trace_endpoint_needs_operator_key():
    from fastapi.testclient import TestClient

    from falcon_sentinel.main import app

    assert TestClient(app).get("/internal/incidents/inc_X/trace").status_code == 401
