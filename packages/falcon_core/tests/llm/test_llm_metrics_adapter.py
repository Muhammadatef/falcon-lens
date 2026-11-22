"""TelemetryMetrics adapter against prometheus metrics shaped like falcon_core.telemetry.metrics (PR #14)."""

from __future__ import annotations

from types import SimpleNamespace

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from falcon_core.llm import metrics as m
from falcon_core.llm.metrics import InMemoryMetrics, TelemetryMetrics, default_metrics


def _fake_module() -> tuple[SimpleNamespace, CollectorRegistry]:
    reg = CollectorRegistry()
    mod = SimpleNamespace(
        LLM_TOKENS=Counter("fl_llm_tokens_total", "d", ("model", "role"), registry=reg),
        LLM_COST=Counter("fl_llm_cost_usd_total", "d", ("model",), registry=reg),
        LLM_FALLBACK=Counter("fl_llm_fallback_total", "d", ("role",), registry=reg),
        CANARY_LEAK=Counter("fl_canary_leak_total", "d", registry=reg),
        ROUTE_AGREEMENT=Gauge("fl_route_agreement_ratio", "d", registry=reg),
        AGENT_STEPS=Histogram("fl_agent_steps", "d", buckets=(1.0, 6.0), registry=reg),
        TOOL_ERRORS=Counter("fl_tool_errors_total", "d", ("tool", "reason"), registry=reg),
        INJECTION=Counter("fl_injection_detected_total", "d", registry=reg),
    )
    return mod, reg


def test_adapter_maps_names_and_labels() -> None:
    mod, reg = _fake_module()
    sink = TelemetryMetrics(mod)
    sink.inc(m.LLM_TOKENS, 120, model="claude-haiku-5-5", role="extractor")
    sink.inc(m.LLM_COST, 0.002, model="claude-haiku-5-5")
    sink.inc(m.LLM_FALLBACK, role="investigator")
    sink.inc(m.CANARY_LEAK, role="extractor")  # extra label dropped
    sink.inc(m.TOOL_ERRORS, tool="render_page", reason="provenance")
    sink.inc(m.INJECTION_DETECTED, source="tool_provenance")
    sink.observe(m.AGENT_STEPS, 3.0)
    sink.observe(m.ROUTE_AGREEMENT, 1.0, role="extractor")
    sink.observe(m.ROUTE_AGREEMENT, 0.0, role="extractor")
    sink.inc("fl_unknown_total")  # ignored

    def v(name: str, **labels: str) -> float | None:
        return reg.get_sample_value(name, labels)

    assert v("fl_llm_tokens_total", model="claude-haiku-5-5", role="extractor") == 120
    assert v("fl_llm_cost_usd_total", model="claude-haiku-5-5") == 0.002
    assert v("fl_llm_fallback_total", role="investigator") == 1
    assert v("fl_canary_leak_total") == 1
    assert v("fl_tool_errors_total", tool="render_page", reason="provenance") == 1
    assert v("fl_injection_detected_total") == 1
    assert v("fl_agent_steps_count") == 1
    assert v("fl_route_agreement_ratio") == 0.5


def test_default_metrics_falls_back_without_telemetry() -> None:
    sink = default_metrics()
    try:
        import falcon_core.telemetry.metrics  # noqa: F401
    except ImportError:
        assert isinstance(sink, InMemoryMetrics)
    else:
        assert isinstance(sink, TelemetryMetrics)
