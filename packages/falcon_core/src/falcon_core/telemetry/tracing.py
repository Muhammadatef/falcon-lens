"""OpenTelemetry tracing: verdict_id on every span, OTLP export to the otel-collector.

The collector forwards traces to Phoenix (the LLM tracer). LLM spans use the
OpenInference attribute names so Phoenix renders them as LLM calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import Token

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from falcon_core.telemetry.logging import incident_id_var, verdict_id_var

log = logging.getLogger("falcon.tracing")
_TRACER_NAME = "falcon_core"


class CorrelationProcessor(SpanProcessor):
    """Stamps verdict_id / incident_id (from the logging contextvars) on every new span."""

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        verdict_id = verdict_id_var.get()
        if verdict_id:
            span.set_attribute("verdict_id", verdict_id)
        incident_id = incident_id_var.get()
        if incident_id:
            span.set_attribute("incident_id", incident_id)

    def on_end(self, span: ReadableSpan) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def build_provider(
    service: str, exporter: SpanExporter | None = None, version: str = "0.1.0"
) -> TracerProvider:
    provider = TracerProvider(
        resource=Resource.create({"service.name": service, "service.version": version})
    )
    provider.add_span_processor(CorrelationProcessor())
    if exporter is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def setup_tracing(service: str, endpoint: str | None = None) -> TracerProvider:
    """Install the global provider. Exports OTLP/gRPC to ``endpoint`` (default
    ``OTEL_EXPORTER_OTLP_ENDPOINT``); with no endpoint spans are created but not exported."""
    endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    exporter: SpanExporter | None = None
    if endpoint and os.environ.get("OTEL_SDK_DISABLED", "").lower() != "true":
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=endpoint.startswith("http://"))
    provider = build_provider(service, exporter)
    trace.set_tracer_provider(provider)
    return provider


def get_tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def verdict_context(verdict_id: str) -> Iterator[None]:
    """Bind verdict_id for logs and spans created inside the block."""
    token: Token[str | None] = verdict_id_var.set(verdict_id)
    try:
        yield
    finally:
        verdict_id_var.reset(token)


@contextmanager
def verdict_span(name: str, verdict_id: str) -> Iterator[trace.Span]:
    """Root/child span for one check with ``verdict_id`` bound for logs too."""
    with verdict_context(verdict_id), get_tracer().start_as_current_span(name) as span:
        span.set_attribute("verdict_id", verdict_id)
        yield span


@contextmanager
def llm_span(
    *,
    model: str,
    role: str,
    verdict_id: str | None = None,
    provider: str | None = None,
) -> Iterator[trace.Span]:
    """Span for one LLM call (OpenInference attributes). Set token counts on exit via
    ``set_llm_usage``. Prompts and outputs are NOT recorded: untrusted text stays out."""
    vid = verdict_id or verdict_id_var.get()
    with get_tracer().start_as_current_span(f"llm.{role}") as span:
        span.set_attribute("openinference.span.kind", "LLM")
        span.set_attribute("llm.model_name", model)
        span.set_attribute("fl.llm.role", role)
        if provider:
            span.set_attribute("llm.provider", provider)
        if vid:
            span.set_attribute("verdict_id", vid)
        yield span


def set_llm_usage(
    span: trace.Span, *, input_tokens: int, output_tokens: int, cost_usd: float | None = None
) -> None:
    span.set_attribute("llm.token_count.prompt", input_tokens)
    span.set_attribute("llm.token_count.completion", output_tokens)
    span.set_attribute("llm.token_count.total", input_tokens + output_tokens)
    if cost_usd is not None:
        span.set_attribute("fl.llm.cost_usd", cost_usd)
