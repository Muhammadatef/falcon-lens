"""Each verdict records the W3C trace id of its check span (contracts/verdict.schema.json `trace_id`)."""

from __future__ import annotations

import re

import pytest
from cascade_helpers import assert_valid, make_cascade, run
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from falcon_core.cascade import CallbackSink, StubSandboxClient, new_verdict_id
from falcon_core.cascade.testing import DEMO_BENIGN_URL, benign_features
from falcon_core.telemetry import tracing

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _install(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = tracing.build_provider("t")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "get_tracer", lambda: provider.get_tracer("t"))
    return exporter


async def test_url_verdict_carries_the_root_span_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = _install(monkeypatch)
    cascade, _ = make_cascade(sandbox=StubSandboxClient(default=benign_features()))
    sink = await run(cascade, DEMO_BENIGN_URL)
    final = sink.docs[-1]
    assert_valid(final)
    assert HEX32.match(final["trace_id"])
    roots = [s for s in exporter.get_finished_spans() if s.name == "cascade.url"]
    assert [format(s.context.trace_id, "032x") for s in roots] == [final["trace_id"]]
    assert all(d["trace_id"] == final["trace_id"] for d in sink.docs)


async def test_message_verdict_has_a_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    cascade, _ = make_cascade(sandbox=StubSandboxClient(default=benign_features()))
    sink = CallbackSink()
    await cascade.run_input(new_verdict_id(), "message", b"See you on Saturday.", sink)
    assert_valid(sink.docs[-1])
    assert HEX32.match(sink.docs[-1]["trace_id"])


async def test_no_tracing_means_no_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "get_tracer", lambda: trace.NoOpTracer())
    cascade, _ = make_cascade(sandbox=StubSandboxClient(default=benign_features()))
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    assert "trace_id" not in final
