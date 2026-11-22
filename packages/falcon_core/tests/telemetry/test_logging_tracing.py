from __future__ import annotations

import json
import logging

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from falcon_core.telemetry import tracing
from falcon_core.telemetry.logging import (
    JsonFormatter,
    incident_id_var,
    sanitize,
    verdict_id_var,
)


def _rec(msg: str, **extra: object) -> logging.LogRecord:
    r = logging.LogRecord("t", logging.INFO, __file__, 1, msg, (), None)
    r.__dict__.update(extra)
    return r


def test_log_carries_ids() -> None:
    t1 = verdict_id_var.set("v-1")
    t2 = incident_id_var.set("inc-1")
    try:
        data = json.loads(JsonFormatter("svc").format(_rec("hello")))
    finally:
        verdict_id_var.reset(t1)
        incident_id_var.reset(t2)
    assert data["verdict_id"] == "v-1"
    assert data["incident_id"] == "inc-1"
    assert data["service"] == "svc"


def test_log_injection_is_neutralised() -> None:
    evil = 'http://a.test/\n{"level":"error","msg":"forged"}\r\x1b[31m ‮'
    line = JsonFormatter("svc").format(_rec(evil, url=evil))
    assert "\n" not in line and "\r" not in line and "\x1b" not in line
    assert " " not in line and "‮" not in line
    data = json.loads(line)  # still exactly one JSON object
    assert data["level"] == "info"
    assert "\\n" in data["msg"] and "\\u001b" in data["msg"]


def test_sanitize_truncates() -> None:
    assert sanitize("a" * 10_000).endswith("[truncated]")


def test_spans_carry_verdict_id() -> None:
    exporter = InMemorySpanExporter()
    provider = tracing.build_provider("t")
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("t")
    token = verdict_id_var.set("v-9")
    try:
        with tracer.start_as_current_span("check"):
            pass
    finally:
        verdict_id_var.reset(token)
    (span,) = exporter.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["verdict_id"] == "v-9"
    assert span.resource.attributes["service.name"] == "t"


def test_setup_tracing_without_endpoint_does_not_export(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    provider = tracing.setup_tracing("svc")
    assert provider is not None
