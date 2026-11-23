"""Per-call LLM metrics (fl_llm_calls_total, fl_llm_call_seconds, fl_llm_results_total) and the shared registry."""

from __future__ import annotations

from typing import Any

from prometheus_client import CollectorRegistry
from pydantic import BaseModel, ConfigDict

from falcon_core.cascade.metrics import CascadeMetrics
from falcon_core.llm import metrics as m
from falcon_core.llm.config import RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics, TelemetryMetrics
from falcon_core.llm.providers import ProviderError
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.llm.testing import ScriptedProvider
from falcon_core.telemetry import metrics as tm

CANARY = "FLC-0123456789ab"
GOOD = '{"label": "x", "n": 1}'


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    n: int


def _fallback() -> Out:
    return Out(label="template", n=0)


def cloud_cfg(**kw: Any) -> RouterConfig:
    return RouterConfig(anthropic_api_key="sk-test", **kw)


def req(**kw: Any) -> JsonRequest[Out]:
    base: dict[str, Any] = {"role": "extractor", "task": "Test task.", "schema": Out}
    base.update(kw)
    return JsonRequest(**base)


def make(
    cfg: RouterConfig, cloud: ScriptedProvider | None, local: ScriptedProvider
) -> tuple[LLMRouter, InMemoryMetrics]:
    mx = InMemoryMetrics()
    return LLMRouter(cfg, cloud=cloud, local=local, metrics=mx, canary=CANARY), mx


async def test_ok_call_counts_call_latency_and_result() -> None:
    router, mx = make(RouterConfig(), None, ScriptedProvider("local", [GOOD]))
    await router.complete_json(req())
    assert mx.get(m.LLM_CALLS, role="extractor", route="local", outcome="ok") == 1
    assert len(mx.values(m.LLM_CALL_SECONDS, role="extractor", route="local")) == 1
    assert mx.get(m.LLM_RESULTS, role="extractor", status="ok") == 1


async def test_cloud_timeout_then_local_ok_records_both_calls() -> None:
    cloud = ScriptedProvider("cloud", [GOOD], delay_s=0.5)
    router, mx = make(cloud_cfg(cloud_timeout_s=0.05), cloud, ScriptedProvider("local", [GOOD]))
    await router.complete_json(req())
    assert mx.get(m.LLM_CALLS, route="cloud", outcome="timeout") == 1
    assert mx.get(m.LLM_CALLS, route="local", outcome="ok") == 1
    assert mx.get(m.LLM_RESULTS, status="ok") == 1


async def test_all_routes_down_counts_template_fallback_result() -> None:
    cloud = ScriptedProvider("cloud", [ProviderError("error")])
    local = ScriptedProvider("local", [ProviderError("timeout")])
    router, mx = make(cloud_cfg(), cloud, local)
    res = await router.complete_json(req(fallback=_fallback))
    assert res.status == "fallback"
    assert mx.get(m.LLM_RESULTS, role="extractor", status="fallback") == 1
    assert mx.get(m.LLM_CALLS, route="cloud", outcome="error") == 1
    assert mx.get(m.LLM_CALLS, route="local", outcome="timeout") == 1


def test_telemetry_adapter_maps_new_names_onto_the_shared_registry() -> None:
    sink = TelemetryMetrics(tm)
    before = tm.REGISTRY.get_sample_value("fl_llm_calls_total", {"role": "r", "route": "local", "outcome": "ok"}) or 0
    sink.inc(m.LLM_CALLS, role="r", route="local", outcome="ok")
    sink.observe(m.LLM_CALL_SECONDS, 0.3, role="r", route="local")
    sink.inc(m.LLM_RESULTS, role="r", status="ok")
    sink.inc(m.AGENT_TOOL_CALLS, tool="x", status="ok")
    got = tm.REGISTRY.get_sample_value("fl_llm_calls_total", {"role": "r", "route": "local", "outcome": "ok"})
    assert got == before + 1
    assert tm.REGISTRY.get_sample_value("fl_llm_call_seconds_count", {"role": "r", "route": "local"}) >= 1
    assert tm.REGISTRY.get_sample_value("fl_llm_results_total", {"role": "r", "status": "ok"}) >= 1


def test_cascade_metrics_record_result_counts_rules_and_unique_signals() -> None:
    class Rule:
        rule_id = "H2"
        effect = "floor_dangerous"

    class Ev:
        def __init__(self, signal: str) -> None:
            self.signal = signal

    class Result:
        fired_rules = (Rule(),)
        degraded_reasons = ("sandbox_unavailable:timeout", "sandbox_unavailable:timeout")
        weighted_evidence = (Ev("url.entropy"), Ev("url.entropy"), Ev("rep.openphish"))

    reg = CollectorRegistry()
    cm = CascadeMetrics(reg)
    cm.record_result(Result())
    assert reg.get_sample_value("fl_hard_rule_fired_total", {"rule": "H2", "effect": "floor_dangerous"}) == 1
    assert reg.get_sample_value("fl_evidence_total", {"signal": "url.entropy"}) == 1  # per verdict, not per item
    assert reg.get_sample_value("fl_evidence_total", {"signal": "rep.openphish"}) == 1
    assert reg.get_sample_value("fl_degraded_reasons_total", {"reason": "sandbox_unavailable:timeout"}) == 1
    cm.sandbox_renders.labels("ok").inc()
    assert reg.get_sample_value("fl_sandbox_renders_total", {"outcome": "ok"}) == 1


def test_out_model_is_importable_for_reuse() -> None:
    assert Out(label="a", n=1).n == 1


async def test_tool_registry_counts_calls_and_buckets_invented_tool_names() -> None:
    from falcon_core.tools import ProvenanceContext, ToolBackends, ToolRegistry
    from falcon_core.tools.registry import Action

    mx = InMemoryMetrics()
    reg = ToolRegistry(ToolBackends(), metrics=mx)
    out = await reg.execute(Action(tool="delete_everything"), ProvenanceContext("https://a.example/", (), frozenset()))
    assert out.status == "rejected"
    assert mx.get(m.AGENT_TOOL_CALLS, tool="unknown", status="rejected") == 1  # never the model-chosen name
    assert mx.get(m.TOOL_ERRORS, reason="unknown_tool") == 1
