from __future__ import annotations

import json
import random
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest
from pydantic import BaseModel, ConfigDict

from falcon_core.llm import metrics as m
from falcon_core.llm.accounting import Usage, cost_usd
from falcon_core.llm.config import ROLES, RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics
from falcon_core.llm.providers import (
    AnthropicProvider,
    ChatTurn,
    OllamaProvider,
    ProviderError,
    ProviderRequest,
)
from falcon_core.llm.router import JsonRequest, LLMRouter, ShadowSample
from falcon_core.llm.spotlight import UntrustedText
from falcon_core.llm.testing import ScriptedProvider

CANARY = "FLC-0123456789ab"
GOOD = '{"label": "x", "n": 1}'


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    n: int


def _fallback() -> Out:
    return Out(label="template", n=0)


def req(**kw: Any) -> JsonRequest[Out]:
    base: dict[str, Any] = {"role": "extractor", "task": "Test task.", "schema": Out}
    base.update(kw)
    return JsonRequest(**base)


def cloud_cfg(**kw: Any) -> RouterConfig:
    return RouterConfig(anthropic_api_key="sk-test", **kw)


def make(
    cfg: RouterConfig, cloud: ScriptedProvider | None, local: ScriptedProvider, **kw: Any
) -> tuple[LLMRouter, InMemoryMetrics]:
    mx = InMemoryMetrics()
    return LLMRouter(cfg, cloud=cloud, local=local, metrics=mx, canary=CANARY, **kw), mx


# --- routing -------------------------------------------------------------------------------------


def test_no_api_key_routes_everything_local() -> None:
    local = ScriptedProvider("local", [GOOD])
    router, _ = make(RouterConfig(), None, local)
    for role in ROLES:
        assert router.primary_route(role) == "local"
        assert [p[0] for p in router.plan(role)] == ["local"]


async def test_no_api_key_call_goes_local() -> None:
    local = ScriptedProvider("local", [GOOD])
    cloud = ScriptedProvider("cloud", [GOOD])
    router, _ = make(RouterConfig(), cloud, local)  # cloud provider ignored without a key
    res = await router.complete_json(req())
    assert res.route == "local" and res.status == "ok" and res.value == Out(label="x", n=1)
    assert cloud.calls == 0 and local.calls == 1
    assert res.cost_usd == 0.0


async def test_sovereign_mode_forces_local_even_with_key() -> None:
    local = ScriptedProvider("local", [GOOD])
    cloud = ScriptedProvider("cloud", [GOOD])
    router, _ = make(cloud_cfg(sovereign_mode=True), cloud, local)
    res = await router.complete_json(req())
    assert res.route == "local" and cloud.calls == 0


async def test_cloud_used_when_key_present_and_costed() -> None:
    cloud = ScriptedProvider("cloud", [GOOD], usage=Usage(input_tokens=1000, output_tokens=100))
    local = ScriptedProvider("local", [GOOD])
    router, mx = make(cloud_cfg(), cloud, local)
    res = await router.complete_json(req(role="investigator"))
    assert res.route == "cloud" and res.model == "claude-sonnet-5-5"
    assert local.calls == 0
    assert res.cost_usd == pytest.approx((1000 * 2.0 + 100 * 10.0) / 1e6)
    assert mx.get(m.LLM_COST, model="claude-sonnet-5-5") == pytest.approx(res.cost_usd)
    assert mx.get(m.LLM_TOKENS, role="investigator") == 1100
    assert cloud.requests[0].cache_system is True


async def test_cloud_timeout_falls_back_to_local_and_counts() -> None:
    cloud = ScriptedProvider("cloud", [GOOD], delay_s=0.5)
    local = ScriptedProvider("local", [GOOD])
    router, mx = make(cloud_cfg(cloud_timeout_s=0.05), cloud, local)
    res = await router.complete_json(req())
    assert res.route == "local" and res.fell_back and res.status == "ok"
    assert mx.get(m.LLM_FALLBACK, role="extractor") == 1
    assert res.calls[0].route == "cloud" and res.calls[0].error == "timeout"


async def test_cloud_error_falls_back_to_local_and_counts() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("error", "InternalServerError")])
    local = ScriptedProvider("local", [GOOD])
    router, mx = make(cloud_cfg(), cloud, local)
    res = await router.complete_json(req(role="responder"))
    assert res.route == "local" and res.fell_back
    assert mx.get(m.LLM_FALLBACK, role="responder") == 1


async def test_all_routes_down_returns_template_fallback() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("error")])
    local = ScriptedProvider("local", [ProviderError("timeout")])
    router, _ = make(cloud_cfg(), cloud, local)
    res = await router.complete_json(req(fallback=_fallback))
    assert res.status == "fallback" and res.route == "none" and res.value == _fallback()


async def test_overall_deadline_skips_fallback_when_exhausted() -> None:
    cloud = ScriptedProvider("cloud", [GOOD], delay_s=0.3)
    local = ScriptedProvider("local", [GOOD])
    router, _ = make(cloud_cfg(), cloud, local)
    res = await router.complete_json(req(timeout_s=0.1, fallback=_fallback))
    assert res.status == "fallback" and local.calls == 0


# --- redaction / spotlighting reach the provider ----------------------------------------------


async def test_redaction_applied_before_cloud_call() -> None:
    cloud = ScriptedProvider("cloud", [GOOD])
    router, _ = make(cloud_cfg(), cloud, ScriptedProvider("local", [GOOD]))
    text = "Pay now. EID 784-1990-1234567-1, card 4111 1111 1111 1111, call 0501234567, a@b.example"
    res = await router.complete_json(req(untrusted=[UntrustedText("message_body", text)]))
    sent = cloud.requests[0].turns[-1].content
    for secret in ("784-1990-1234567-1", "4111 1111 1111 1111", "0501234567", "a@b.example"):
        assert secret not in sent
    assert "[EMIRATES_ID]" in sent and "[CARD]" in sent and "[PHONE]" in sent
    assert res.redactions == {"email": 1, "emirates_id": 1, "card": 1, "phone": 1}


@pytest.mark.parametrize(
    "secret",
    [
        "784-1990-123\u200b4567-1",
        "٧٨٤-١٩٩٠-١٢٣٤٥٦٧-١",
        "٤١١١ ١١١١ ١١١١ ١١١١",
        "4111.1111.1111.1111",
        "٠٥٠١٢٣٤٥٦٧",
        "a.b＠exa\u200bmple.ae",
    ],
)
async def test_normalised_redaction_on_the_cloud_request(secret: str) -> None:
    cloud = ScriptedProvider("cloud", [GOOD])
    router, _ = make(cloud_cfg(), cloud, ScriptedProvider("local", [GOOD]))
    await router.complete_json(req(untrusted=[UntrustedText("message_body", f"pay: {secret}")], context=secret))
    sent = cloud.requests[0].turns[-1].content
    assert not any(c.isdigit() and not c.isascii() for c in sent)
    assert "@" not in sent and "＠" not in sent and "\u200b" not in sent
    body = sent.split("kind=message_body>>>", 1)[1]
    assert not any(c.isdigit() for c in body.split("<<<END_UNTRUSTED", 1)[0])


async def test_untrusted_text_is_spotlighted_and_system_is_stable() -> None:
    cloud = ScriptedProvider("cloud", [GOOD])
    router, _ = make(cloud_cfg(), cloud, ScriptedProvider("local", [GOOD]))
    for _ in range(2):
        await router.complete_json(req(untrusted=[UntrustedText("page_visible_text", "a\nb")]))
    r1, r2 = cloud.requests
    assert r1.system == r2.system  # cacheable
    assert CANARY in r1.system
    u1, u2 = r1.turns[-1].content, r2.turns[-1].content
    assert "<<<UNTRUSTED:" in u1 and "\n^a\n^b\n" in u1
    assert u1 != u2  # fresh nonce per request
    assert CANARY not in u1


# --- canary ------------------------------------------------------------------------------------


async def test_canary_leak_discards_output_and_counts() -> None:
    leak = json.dumps({"label": f"my marker is {CANARY}", "n": 1})
    local = ScriptedProvider("local", [leak, GOOD])
    router, mx = make(RouterConfig(), None, local)
    res = await router.complete_json(req(fallback=_fallback))
    assert res.canary_leak and res.status == "fallback" and res.value == _fallback()
    assert mx.get(m.CANARY_LEAK, role="extractor") == 1
    assert local.calls == 1  # no repair on a compromised reply


async def test_partial_canary_leak_detected() -> None:
    local = ScriptedProvider("local", [json.dumps({"label": "0123456789AB", "n": 1})])
    router, mx = make(RouterConfig(), None, local)
    res = await router.complete_json(req())
    assert res.canary_leak and res.value is None and res.status == "failed"


# --- parsing, repair, fallback -------------------------------------------------------------------


async def test_special_tokens_and_fences_are_handled() -> None:
    local = ScriptedProvider("local", ['Sure:\n```json\n{"label": "x", "n": 1}\n```<|end_message|>'])
    router, _ = make(RouterConfig(), None, local)
    res = await router.complete_json(req())
    assert res.status == "ok" and res.value == Out(label="x", n=1)


async def test_one_repair_retry_then_ok() -> None:
    local = ScriptedProvider("local", ["not json", GOOD])
    router, _ = make(RouterConfig(), None, local)
    res = await router.complete_json(req())
    assert res.status == "repaired" and local.calls == 2
    repair_turns = local.requests[1].turns
    assert repair_turns[-2] == ChatTurn("assistant", "not json")
    assert "could not be used" in repair_turns[-1].content


async def test_repair_fails_then_template() -> None:
    local = ScriptedProvider("local", ['{"label": "x", "n": 1, "score": 0}', '{"label": 5}'])
    router, _ = make(RouterConfig(), None, local)
    res = await router.complete_json(req(fallback=_fallback))
    assert res.status == "fallback" and res.value == _fallback() and local.calls == 2
    assert res.error and "schema violation" in res.error


async def test_no_fallback_means_failed() -> None:
    router, _ = make(RouterConfig(), None, ScriptedProvider("local", ["nope"]))
    res = await router.complete_json(req())
    assert res.status == "failed" and res.value is None and not res.ok


# --- shadow --------------------------------------------------------------------------------------


async def test_shadow_samples_other_route_and_measures_agreement() -> None:
    cloud = ScriptedProvider("cloud", [GOOD])
    local = ScriptedProvider("local", ['{"label": "y", "n": 1}'])
    samples: list[ShadowSample] = []

    async def hook(s: ShadowSample) -> None:
        samples.append(s)

    router, mx = make(
        cloud_cfg(shadow_rate=1.0),
        cloud,
        local,
        shadow_hook=hook,
        rng=random.Random(1),  # noqa: S311
    )
    res = await router.complete_json(req())
    await router.drain_shadow()
    assert res.route == "cloud" and local.calls == 1
    assert samples == [ShadowSample("extractor", "cloud", "local", False, None)]
    assert mx.values(m.ROUTE_AGREEMENT, role="extractor") == [0.0]


async def test_shadow_never_reaches_cloud_in_sovereign_mode() -> None:
    cloud = ScriptedProvider("cloud", [GOOD])
    local = ScriptedProvider("local", [GOOD])
    router, _ = make(cloud_cfg(shadow_rate=1.0, sovereign_mode=True), cloud, local)
    await router.complete_json(req())
    await router.drain_shadow()
    assert cloud.calls == 0


# --- accounting ----------------------------------------------------------------------------------


def test_cost_table() -> None:
    u = Usage(input_tokens=50_000, output_tokens=50_000)
    assert cost_usd("cloud", "claude-haiku-5-5", u) == pytest.approx(0.05 * 0.10 + 0.05 * 0.50)
    big = Usage(input_tokens=200_000, output_tokens=0)
    assert cost_usd("cloud", "claude-haiku-5-5", big) == pytest.approx(0.2 * 0.50)
    cached = Usage(input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    assert cost_usd("cloud", "claude-sonnet-5-5", cached) == pytest.approx(0.10)
    assert cost_usd("local", "inkling-2-mini-chat", u) == 0.0


def test_config_from_env() -> None:
    cfg = RouterConfig.from_env(
        {
            "ANTHROPIC_API_KEY": "sk-x",
            "FL_CLOUD_MODEL_EXTRACTOR": "claude-haiku-5-5",
            "FL_LOCAL_MODEL": "inkling-2-mini-chat",
            "FL_SHADOW_RATE": "7",
            "FL_LLM_TIMEOUT_S": "3.5",
        }
    )
    assert cfg.cloud_enabled and cfg.shadow_rate == 1.0 and cfg.cloud_timeout_s == 3.5
    assert "sk-x" not in repr(cfg)
    assert not RouterConfig.from_env({"ANTHROPIC_API_KEY": "sk-x", "FL_SOVEREIGN_MODE": "true"}).cloud_enabled
    assert not RouterConfig.from_env({}).cloud_enabled


# --- providers -----------------------------------------------------------------------------------


class _FakeMessages:
    def __init__(self, exc: Exception | None = None) -> None:
        self.kwargs: dict[str, Any] = {}
        self.exc = exc

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.exc:
            raise self.exc
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="..."),
                SimpleNamespace(type="text", text=GOOD),
            ],
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                cache_read_input_tokens=600,
                cache_creation_input_tokens=0,
            ),
            model=kwargs["model"],
        )


def _preq(model: str) -> ProviderRequest:
    return ProviderRequest(model=model, system="SYS", turns=(ChatTurn("user", "hi"),), max_tokens=50, timeout_s=3)


async def test_anthropic_request_shape_with_prompt_caching() -> None:
    msgs = _FakeMessages()
    prov = AnthropicProvider("sk", client=SimpleNamespace(messages=msgs))
    resp = await prov.complete(_preq("claude-haiku-5-5"))
    k = msgs.kwargs
    assert k["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert k["thinking"] == {"type": "disabled"} and k["output_config"] == {"effort": "low"}
    assert "temperature" not in k and "tool_choice" not in k
    assert resp.text == GOOD and resp.usage.cache_read_tokens == 600

    await prov.complete(_preq("claude-sonnet-5-5"))
    assert msgs.kwargs["thinking"] == {"type": "between_tools"}  # Sonnet 5.5 rejects "disabled"


async def test_anthropic_errors_map_to_provider_errors() -> None:
    timeout = anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.invalid"))
    prov = AnthropicProvider("sk", client=SimpleNamespace(messages=_FakeMessages(timeout)))
    with pytest.raises(ProviderError) as ei:
        await prov.complete(_preq("claude-haiku-5-5"))
    assert ei.value.kind == "timeout"


async def test_ollama_provider_shape_and_special_token_strip() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": GOOD + "<|end_message|>"}}],
                "usage": {"prompt_tokens": 69, "completion_tokens": 18},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        prov = OllamaProvider("http://ollama.test:11434/", client=client)
        resp = await prov.complete(_preq("inkling-2-mini-chat"))
    assert seen["url"] == "http://ollama.test:11434/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["body"]["stream"] is False and "response_format" not in seen["body"]
    assert resp.text == GOOD and resp.usage.output_tokens == 18


async def test_local_no_think_sends_enable_thinking_false_only_when_set() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": GOOD}}], "usage": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await OllamaProvider("http://gate.test:8085", client=client).complete(_preq("q"))
        await OllamaProvider("http://gate.test:8085", client=client, no_think=True).complete(_preq("q"))
    assert "chat_template_kwargs" not in bodies[0]
    assert bodies[1]["chat_template_kwargs"] == {"enable_thinking": False}
    assert RouterConfig.from_env({"FL_LOCAL_NO_THINK": "1"}).local_no_think
    assert not RouterConfig.from_env({}).local_no_think


async def test_ollama_http_error_is_provider_error() -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as c:
        with pytest.raises(ProviderError):
            await OllamaProvider("http://ollama.test:11434", client=c).complete(_preq("m"))
