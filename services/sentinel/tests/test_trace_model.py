from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from graph_helpers import make_env
from jsonschema import Draft202012Validator

from falcon_core.telemetry import tracing
from falcon_sentinel.llm import RouterLLM, StubLLM
from falcon_sentinel.trace import assemble_trace

SCHEMA = Path(__file__).resolve().parents[3] / "contracts" / "agent_trace.schema.json"


class _FakeRouterLLM:
    """Reports a router-style model id; the trace must carry it, not the string "stub"."""

    route = "cloud"
    model = "claude-haiku-5-5"

    def __init__(self) -> None:
        self._stub = StubLLM()

    async def complete_json(self, **kw: Any) -> dict[str, Any]:
        return await self._stub.complete_json(**kw)


async def _llm_steps(env: Any, iid: str) -> list[dict[str, Any]]:
    doc = assemble_trace(iid, await env.repo.trace_list(iid))
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(doc)
    (run,) = doc["runs"]
    return [s["llm"] for s in run["steps"] if s["llm"]]


async def test_run_records_the_triage_span_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = tracing.build_provider("t")
    monkeypatch.setattr(tracing, "get_tracer", lambda: provider.get_tracer("t"))
    env = await make_env()
    iid = env.campaign_id()
    await env.runner(StubLLM()).run(iid)
    doc = assemble_trace(iid, await env.repo.trace_list(iid))
    Draft202012Validator(json.loads(SCHEMA.read_text())).validate(doc)
    assert re.fullmatch(r"[0-9a-f]{32}", doc["runs"][0]["trace_id"])


async def test_trace_records_the_actual_model_id() -> None:
    env = await make_env()
    iid = env.campaign_id()
    await env.runner(_FakeRouterLLM()).run(iid)
    llms = await _llm_steps(env, iid)
    assert llms and {x["model"] for x in llms} == {"claude-haiku-5-5"} and {x["route"] for x in llms} == {"cloud"}


async def test_stub_is_recorded_only_when_the_stub_provider_ran() -> None:
    env = await make_env()
    iid = env.campaign_id()
    await env.runner().run(iid)
    llms = [x for x in await _llm_steps(env, iid) if x["route"] != "none"]
    assert llms and {x["model"] for x in llms} == {"stub"}


def test_router_llm_reports_the_model_that_answered() -> None:
    llm = RouterLLM(router=None)  # type: ignore[arg-type]
    assert llm.model == "unknown"
    llm._last_model = "inkling-2-mini-chat"
    assert llm.model == "inkling-2-mini-chat"
