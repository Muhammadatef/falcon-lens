"""Every LLM failure class ends in the template fallback and the graph still reaches the approval interrupt."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from graph_helpers import make_env

from falcon_sentinel.llm import AnthropicLLM, LLMOutputError, OpenAICompatLLM, parse_json_text


def transport_llm(handler: Any, **kw: Any) -> OpenAICompatLLM:
    return OpenAICompatLLM("http://llm.test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


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


@pytest.mark.parametrize("case", list(CASES))
async def test_llm_failure_falls_back_to_template_and_reaches_interrupt(case: str) -> None:
    env = await make_env()
    iid = env.campaign_id()
    state = await env.runner(transport_llm(CASES[case])).run(iid)
    inc = env.cache.get(iid)
    assert inc is not None
    assert inc["summary"]["generated_by"] == "template" and inc["summary"]["model_route"] == "none"
    assert inc["summary"]["en"] and inc["summary"]["ar"]
    assert inc["severity_reason"]["en"]
    assert inc["status"] == "awaiting_approval" and state["__interrupt__"]
    assert all(a["status"] != "sent" for a in inc["actions"])


async def test_no_response_format_on_local_route_by_default() -> None:
    bodies: list[dict[str, Any]] = []

    def h(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _ok('```json\n{"a": 1}\n```<|end_message|>')

    llm = transport_llm(h)
    assert await llm.complete_json(role="sentinel", system="s", user_json={}, schema={}) == {"a": 1}
    assert "response_format" not in bodies[0]


async def test_structured_rejected_retries_once_without_and_remembers() -> None:
    bodies: list[dict[str, Any]] = []

    def h(request: httpx.Request) -> httpx.Response:
        b = json.loads(request.content)
        bodies.append(b)
        if "response_format" in b:
            return httpx.Response(501, json={"error": "structured output is unavailable"})
        return _ok('{"a": 1}')

    llm = transport_llm(h, structured=True)
    assert await llm.complete_json(role="sentinel", system="s", user_json={}, schema={}) == {"a": 1}
    assert await llm.complete_json(role="sentinel", system="s", user_json={}, schema={}) == {"a": 1}
    assert ["response_format" in b for b in bodies] == [True, False, False]


def test_parse_json_text_variants() -> None:
    assert parse_json_text('prose {"a": 2} tail') == {"a": 2}
    with pytest.raises(LLMOutputError):
        parse_json_text("[1]")


async def test_anthropic_errors_map_to_template() -> None:
    env = await make_env()
    iid = env.campaign_id()
    llm = AnthropicLLM(
        "k", client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(529, text="overloaded")))
    )
    await env.runner(llm).run(iid)
    assert (env.cache.get(iid) or {})["summary"]["generated_by"] == "template"


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
