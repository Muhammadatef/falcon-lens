"""LLM router and cascade tier spans: useful attributes, never untrusted text."""

from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel, ConfigDict

from falcon_core.llm.config import RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.llm.spotlight import UntrustedText
from falcon_core.llm.testing import ScriptedProvider
from falcon_core.telemetry import tracing

SECRET_TEXT = "pay now at http://user:pw@evil.example/login"


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


def _install(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = tracing.build_provider("t")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "get_tracer", lambda: provider.get_tracer("t"))
    return exporter


async def test_router_call_emits_llm_span_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _install(monkeypatch)
    local = ScriptedProvider("local", ['{"label": "x"}'])
    router = LLMRouter(RouterConfig(), cloud=None, local=local, metrics=InMemoryMetrics(), canary="FLC-0123456789ab")
    req = JsonRequest(
        role="extractor",
        task="Test task.",
        schema=Out,
        untrusted=[UntrustedText("page", SECRET_TEXT)],
        verdict_id="v-7",
    )
    with tracing.verdict_span("cascade.url", "v-7"):
        res = await router.complete_json(req)
    assert res.ok
    spans = {s.name: s for s in exporter.get_finished_spans()}
    sp = spans["llm.extractor"]
    attrs = dict(sp.attributes or {})
    assert attrs["openinference.span.kind"] == "LLM"
    assert attrs["fl.llm.role"] == "extractor"
    assert attrs["fl.llm.route"] == "local"
    assert attrs["llm.provider"] == "ollama"
    assert attrs["verdict_id"] == "v-7"
    assert attrs["llm.token_count.prompt"] == 100 and attrs["gen_ai.usage.output_tokens"] == 20
    assert "fl.latency_ms" in attrs
    assert set(attrs) <= tracing.LLM_SPAN_ATTRIBUTES
    assert "evil.example" not in repr(attrs) and "user:pw" not in repr(attrs)
    assert sp.parent is not None  # nested under the verdict span


def test_fl_span_drops_unknown_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _install(monkeypatch)
    with tracing.fl_span("cascade.T1", "CHAIN", **{"fl.tier": "T1", "url": SECRET_TEXT, "fl.node": None}):
        pass
    (done,) = exporter.get_finished_spans()
    attrs = dict(done.attributes or {})
    assert attrs == {"openinference.span.kind": "CHAIN", "fl.tier": "T1"}


def test_setup_tracing_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert tracing.setup_tracing("a") is tracing.setup_tracing("b")


def test_create_app_installs_exporting_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every service builds its app with create_app, which installs the provider + OTLP exporter."""
    from opentelemetry.sdk.trace import TracerProvider

    from falcon_core.service import create_app

    monkeypatch.setattr(tracing, "_installed", None)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    create_app("svc-test")
    provider = tracing._installed
    assert isinstance(provider, TracerProvider)
    procs = provider._active_span_processor._span_processors
    assert any(type(p).__name__ == "BatchSpanProcessor" for p in procs)
    monkeypatch.setattr(tracing, "_installed", None)


class GraphInterrupt(Exception):  # same class name LangGraph raises for a human-approval pause
    pass


def test_interrupt_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _install(monkeypatch)
    with pytest.raises(GraphInterrupt), tracing.fl_span("sentinel.act"):
        raise GraphInterrupt("waiting")
    (done,) = exporter.get_finished_spans()
    assert done.status.status_code.name == "UNSET"
    assert dict(done.attributes or {})["fl.interrupted"] is True
