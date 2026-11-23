"""Sentinel LLM access goes through falcon_core's router; every failure class ends in the template fallback and
the graph still reaches the approval interrupt."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from graph_helpers import make_env

from falcon_core.llm import LLMRouter, OllamaProvider, RouterConfig
from falcon_core.llm.providers import ProviderError
from falcon_core.llm.testing import ScriptedProvider
from falcon_sentinel.llm import LLMOutputError, LLMUnavailable, RouterLLM, SummaryOut, structured


def local_router(handler: Any) -> LLMRouter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLMRouter(RouterConfig(), local=OllamaProvider("http://llm.test", client=client))


def _ok(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _refused(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


def _timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


CASES = {
    "501": lambda r: httpx.Response(501, json={"error": "structured output is unavailable"}),
    "500": lambda r: httpx.Response(500, text="boom"),
    "refused": _refused,
    "timeout": _timeout,
    "garbage": lambda r: _ok("I am sorry, no json here <|end_message|>"),
}


def td_of(inc: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in inc["actions"] if a["tool"] == "draft_takedown"]


@pytest.mark.parametrize("case", list(CASES))
async def test_llm_failure_falls_back_to_template_and_reaches_interrupt(case: str) -> None:
    env = await make_env()
    iid = env.campaign_id()
    state = await env.runner(RouterLLM(local_router(CASES[case]))).run(iid)
    inc = env.cache.get(iid)
    assert inc is not None
    assert inc["summary"]["generated_by"] == "template" and inc["summary"]["model_route"] == "none"
    assert inc["summary"]["en"] and inc["summary"]["ar"]
    assert inc["severity_reason"]["en"]
    assert inc["status"] == "awaiting_approval" and state["__interrupt__"]
    assert all(a["status"] != "sent" for a in inc["actions"])


async def test_no_response_format_sent_on_local_route() -> None:
    bodies: list[dict[str, Any]] = []

    def h(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _ok('```json\n{"en": "a", "ar": "b", "claims": []}\n```<|end_message|>')

    out = await structured(
        RouterLLM(local_router(h)), SummaryOut, system="sys", user_json={"task": "summarise", "evidence": {}}
    )
    assert out.en == "a"
    assert bodies and all("response_format" not in b for b in bodies)


async def test_phone_and_correlation_values_are_redacted_before_the_cloud_route() -> None:
    cloud = ScriptedProvider("cloud", ['{"en": "x", "ar": "y", "claims": []}'])
    local = ScriptedProvider("local", ["{}"])
    router = LLMRouter(RouterConfig(anthropic_api_key="k"), cloud=cloud, local=local)
    evidence = {
        "indicators": [{"kind": "phone", "value": "+971 50 123 4567", "value_defanged": "+971 50 123 4567"}],
        "correlation_keys": {"contact": ["0501234567", "mail victim@example.org"]},
    }
    llm = RouterLLM(router)
    await structured(llm, SummaryOut, system="sys", user_json={"task": "summarise", "evidence": evidence})
    assert llm.route == "cloud" and local.calls == 0
    (req,) = cloud.requests
    sent = req.system + "".join(t.content for t in req.turns)
    for raw in ("123 4567", "0501234567", "victim@example.org"):
        assert raw not in sent
    assert "[PHONE]" in sent and "[EMAIL]" in sent


async def test_sovereign_mode_never_reaches_cloud() -> None:
    cloud = ScriptedProvider("cloud", ['{"en": "x", "ar": "y", "claims": []}'])
    local = ScriptedProvider("local", ['{"en": "x", "ar": "y", "claims": []}'])
    router = LLMRouter(RouterConfig(anthropic_api_key="k", sovereign_mode=True), cloud=cloud, local=local)
    llm = RouterLLM(router)
    await structured(llm, SummaryOut, system="sys", user_json={"task": "summarise", "evidence": {}})
    assert cloud.calls == 0 and local.calls == 1 and llm.route == "local"


async def test_cloud_error_falls_back_to_local_through_router() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("error", "boom")])
    local = ScriptedProvider("local", ['{"en": "x", "ar": "y", "claims": []}'])
    llm = RouterLLM(LLMRouter(RouterConfig(anthropic_api_key="k"), cloud=cloud, local=local))
    await structured(llm, SummaryOut, system="sys", user_json={"task": "summarise", "evidence": {}})
    assert llm.route == "local"


async def test_tokens_counted_even_when_output_is_unparseable() -> None:
    local = ScriptedProvider("local", ["not json at all"])
    llm = RouterLLM(LLMRouter(RouterConfig(), local=local))
    seen: list[int] = []
    with pytest.raises(LLMOutputError) as ei:
        await structured(llm, SummaryOut, system="s", user_json={"task": "x"}, on_tokens=seen.append)
    assert not isinstance(ei.value, LLMUnavailable)
    assert sum(seen) > 0


async def test_unreachable_model_is_llm_unavailable() -> None:
    llm = RouterLLM(local_router(_refused))
    with pytest.raises(LLMUnavailable):
        await structured(llm, SummaryOut, system="s", user_json={"task": "x"})


# ---- the deterministic fallback takedown draft -------------------------------------------------


async def test_rule_fallback_draft_is_labelled_audited_and_waits_for_approval() -> None:
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner(RouterLLM(local_router(_refused)))
    state = await runner.run(iid)
    inc = env.cache.get(iid)
    assert inc is not None and state["__interrupt__"]
    (td,) = td_of(inc)
    assert td["mode"] == "external_draft" and td["status"] == "awaiting_approval"
    assert td["origin"] == "rule_fallback" and td["approved_by"] is None
    assert td["evidence_ids"] and all(e.startswith("rule:") for e in td["evidence_ids"])
    assert td["draft"]["body_ar"] and td["draft"]["body_en"]
    assert any(t.get("what_en") and t.get("what_ar") and "rule_fallback" in t["what"] for t in inc["timeline"])
    queued = [a for a in await env.repo.audit_list(iid) if a["result"].get("queued") == "rule_fallback"]
    assert len(queued) == 1 and queued[0]["action_id"] == td["action_id"] and queued[0]["mode"] == "external_draft"
    assert [r.url.path for r in env.http_log.requests] == ["/api/v2/alerts"]  # nothing sent externally
    await runner.approve(iid, td["action_id"], "op_alice")
    (td,) = td_of(env.cache.get(iid) or {})
    assert td["status"] == "approved" and td["approved_by"] == "op_alice"


async def test_no_domain_indicator_means_no_fallback_draft_and_no_hang() -> None:
    env = await make_env()
    iid = env.campaign_id()

    def strip(i: dict[str, Any]) -> None:
        i["indicators"] = [x for x in i["indicators"] if x["kind"] != "domain"]

    env.cache.update(iid, strip)
    state = await env.runner(RouterLLM(local_router(_refused))).run(iid)
    inc = env.cache.get(iid)
    assert inc is not None
    assert td_of(inc) == [] and "__interrupt__" not in state
    assert inc["status"] != "triaging"


async def test_requeue_failure_does_not_crash() -> None:
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner()
    calls: list[str] = []

    async def boom(i: str, *a: Any, **k: Any) -> Any:
        calls.append(i)
        raise RuntimeError("db down")

    def set_triaging(i: dict[str, Any]) -> None:
        i["status"] = "triaging"

    env.cache.update(iid, set_triaging)
    runner.run = boom  # type: ignore[method-assign]
    assert await runner.resume_unfinished() == []
    assert calls == [iid]
