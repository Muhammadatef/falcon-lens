"""FL_LLM_ROUTE modes: cloud_with_local_fallback, local, cloud_only, auto; runtime switch via a shared store."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from falcon_core.llm import metrics as m
from falcon_core.llm.config import RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics
from falcon_core.llm.providers import ProviderError
from falcon_core.llm.route import (
    REDIS_KEY,
    RedisRouteSource,
    RouteSetting,
    effective_mode,
    parse_mode,
    write_setting,
)
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.llm.testing import ScriptedProvider

GOOD = '{"label": "x", "n": 1}'


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    n: int


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}

    async def get(self, name: Any) -> Any:
        return self.kv.get(name)

    async def set(self, name: Any, value: Any) -> Any:
        self.kv[name] = value


def cfg(**kw: Any) -> RouterConfig:
    return RouterConfig(anthropic_api_key=kw.pop("key", "sk-test"), **kw)


def req() -> JsonRequest[Out]:
    return JsonRequest(role="extractor", task="t", schema=Out, fallback=lambda: Out(label="tpl", n=0))


def build(
    c: RouterConfig, cloud: ScriptedProvider, local: ScriptedProvider, **kw: Any
) -> tuple[LLMRouter, InMemoryMetrics]:
    mx = InMemoryMetrics()
    return LLMRouter(c, cloud=cloud, local=local, metrics=mx, **kw), mx


async def test_default_with_key_is_cloud_then_local_fallback() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("rate_limit", "RateLimitError")])
    local = ScriptedProvider("local", [GOOD])
    router, mx = build(cfg(), cloud, local)
    res = await router.complete_json(req())
    assert res.ok and res.route == "local" and res.fell_back
    assert res.route_mode == "cloud_with_local_fallback" and res.fallback_reason == "rate_limit"
    assert mx.get(m.LLM_CALLS, role="extractor", route="cloud", outcome="error", fallback="false") == 1
    assert mx.get(m.LLM_CALLS, role="extractor", route="local", outcome="ok", fallback="true") == 1
    assert res.calls[-1].fallback_reason == "rate_limit"


async def test_cloud_ok_does_not_touch_local() -> None:
    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(), cloud, local)
    res = await router.complete_json(req())
    assert res.route == "cloud" and not res.fell_back and local.calls == 0 and res.fallback_reason is None


async def test_local_mode_never_calls_cloud() -> None:
    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(llm_route="local"), cloud, local)
    res = await router.complete_json(req())
    assert res.route == "local" and cloud.calls == 0 and res.route_mode == "local"


async def test_sovereign_env_forces_local_even_if_store_says_cloud() -> None:
    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    r = FakeRedis()
    await write_setting(r, "cloud_only", None, "op")
    router, _ = build(cfg(sovereign_mode=True), cloud, local, route_source=RedisRouteSource(r, ttl_s=0))
    res = await router.complete_json(req())
    assert res.route == "local" and cloud.calls == 0


async def test_cloud_only_has_no_local_fallback() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("timeout")])
    local = ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(llm_route="cloud_only"), cloud, local)
    res = await router.complete_json(req())
    assert res.status == "fallback" and res.route == "none" and local.calls == 0
    assert res.fallback_reason == "timeout" and not res.fell_back


async def test_auto_follows_the_key() -> None:
    local = ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(key=""), ScriptedProvider("cloud", [GOOD]), local)
    res = await router.complete_json(req())
    assert res.route == "local" and res.route_mode == "local"
    router2, _ = build(cfg(), ScriptedProvider("cloud", [GOOD]), local)
    assert (await router2.complete_json(req())).route == "cloud"


async def test_runtime_switch_is_picked_up_without_restart() -> None:
    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    r = FakeRedis()
    now = [0.0]
    src = RedisRouteSource(r, ttl_s=3.0, clock=lambda: now[0])
    router, _ = build(cfg(), cloud, local, route_source=src)
    assert (await router.complete_json(req())).route == "cloud"
    await write_setting(r, "local", None, "op")
    assert (await router.complete_json(req())).route == "cloud"  # cached for a few seconds
    now[0] = 4.0
    res = await router.complete_json(req())
    assert res.route == "local" and cloud.calls == 2


async def test_local_model_choice_and_per_model_base_url() -> None:
    r = FakeRedis()
    await write_setting(r, "local", "qwen3.8:27b", "op")
    c = cfg(local_qwen_base_url="http://gate:8085", local_base_url="http://ollama:11434")
    router = LLMRouter(c, metrics=InMemoryMetrics(), route_source=RedisRouteSource(r, ttl_s=0))
    await router.refresh_route()
    (route, model, prov), *_ = router.plan("extractor")
    assert (route, model) == ("local", "qwen3.8:27b") and prov._url.startswith("http://gate:8085")  # type: ignore[attr-defined]
    assert router.config.local_base_for("inkling-2-mini-chat") == "http://ollama:11434"
    assert prov._no_think is True  # type: ignore[attr-defined]  # qwen via the gate needs FL_LOCAL_NO_THINK behaviour
    assert router._local_for("inkling-2-mini-chat")._no_think is False  # type: ignore[attr-defined]


async def test_no_shadow_to_cloud_in_local_mode() -> None:
    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(llm_route="local", shadow_rate=1.0), cloud, local)
    await router.complete_json(req())
    await router.drain_shadow()
    assert cloud.calls == 0


async def test_broken_store_keeps_working_and_invalid_values_are_ignored() -> None:
    class Boom:
        async def get(self, name: Any) -> Any:
            raise OSError("down")

        async def set(self, name: Any, value: Any) -> Any:
            return None

    cloud, local = ScriptedProvider("cloud", [GOOD]), ScriptedProvider("local", [GOOD])
    router, _ = build(cfg(), cloud, local, route_source=RedisRouteSource(Boom(), ttl_s=0))
    assert (await router.complete_json(req())).route == "cloud"
    r = FakeRedis()
    r.kv[REDIS_KEY] = '{"mode": "evil", "local_model": null}'
    assert await RedisRouteSource(r, ttl_s=0).get() is None
    r.kv[REDIS_KEY] = '{"mode": "local", "local_model": "gpt-9"}'
    assert await RedisRouteSource(r, ttl_s=0).get() is None


@pytest.mark.parametrize(
    ("mode", "sov", "cloud", "want"),
    [
        ("auto", False, True, "cloud_with_local_fallback"),
        ("auto", False, False, "local"),
        ("cloud_with_local_fallback", False, False, "local"),
        ("cloud_only", False, True, "cloud_only"),
        ("cloud_only", True, True, "local"),
        ("local", False, True, "local"),
    ],
)
def test_effective_mode(mode: Any, sov: bool, cloud: bool, want: str) -> None:
    assert effective_mode(mode, sovereign=sov, cloud_available=cloud)[0] == want


def test_parse_mode_and_setting_roundtrip() -> None:
    assert parse_mode("LOCAL ") == "local" and parse_mode("x") is None and parse_mode(None) is None
    s = RouteSetting("local", "qwen3.8:27b", "t", "u")
    assert RouteSetting.from_json(s.to_json()) == s
