"""LLM router, redaction, spotlighting, canary and accounting (T-024)."""

from falcon_core.llm.accounting import Usage, cost_usd
from falcon_core.llm.config import ROLES, Role, Route, RouterConfig
from falcon_core.llm.metrics import InMemoryMetrics, MetricsSink, NullMetrics, TelemetryMetrics, default_metrics
from falcon_core.llm.providers import (
    AnthropicProvider,
    ChatTurn,
    OllamaProvider,
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)
from falcon_core.llm.redaction import RedactionResult, redact, redact_text
from falcon_core.llm.router import JsonRequest, LLMResult, LLMRouter, ShadowSample
from falcon_core.llm.spotlight import UntrustedText, spotlight

__all__ = [
    "ROLES",
    "AnthropicProvider",
    "ChatTurn",
    "InMemoryMetrics",
    "JsonRequest",
    "LLMResult",
    "LLMRouter",
    "MetricsSink",
    "NullMetrics",
    "OllamaProvider",
    "Provider",
    "ProviderError",
    "ProviderRequest",
    "ProviderResponse",
    "RedactionResult",
    "Role",
    "Route",
    "RouterConfig",
    "ShadowSample",
    "TelemetryMetrics",
    "UntrustedText",
    "Usage",
    "cost_usd",
    "default_metrics",
    "redact",
    "redact_text",
    "spotlight",
]
