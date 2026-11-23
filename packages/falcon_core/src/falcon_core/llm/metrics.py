"""Metric sink used by the router, tools and agents.

``docs/OBSERVABILITY.md`` says the ``fl_`` metrics are declared once in
``falcon_core/telemetry/metrics.py`` (builder-observability). Callers use the small sink protocol
below. ``default_metrics()`` returns ``TelemetryMetrics`` (the shared prometheus registry) when that
module is installed, else ``InMemoryMetrics``. Metric names are the contract names.
"""

from __future__ import annotations

import importlib
import threading
from collections import defaultdict, deque
from typing import Any, Protocol

LLM_TOKENS = "fl_llm_tokens_total"  # {model, role}
LLM_COST = "fl_llm_cost_usd_total"  # {model}
LLM_FALLBACK = "fl_llm_fallback_total"  # {role}
CANARY_LEAK = "fl_canary_leak_total"  # {role}
ROUTE_AGREEMENT = "fl_route_agreement_ratio"  # observed per shadow sample {role}
AGENT_STEPS = "fl_agent_steps"  # histogram
TOOL_ERRORS = "fl_tool_errors_total"  # {tool, reason}
INJECTION_DETECTED = "fl_injection_detected_total"  # {source}
LLM_CALLS = "fl_llm_calls_total"  # {role, route, outcome}
LLM_CALL_SECONDS = "fl_llm_call_seconds"  # histogram {role, route}
LLM_RESULTS = "fl_llm_results_total"  # {role, status}
AGENT_TOOL_CALLS = "fl_agent_tool_calls_total"  # {tool, status}

LabelKey = tuple[tuple[str, str], ...]


class MetricsSink(Protocol):
    def inc(self, name: str, value: float = 1.0, **labels: str) -> None: ...

    def observe(self, name: str, value: float, **labels: str) -> None: ...


class InMemoryMetrics:
    """Thread-safe counters and observation lists keyed by (name, sorted labels)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple[str, LabelKey], float] = defaultdict(float)
        self.observations: dict[tuple[str, LabelKey], list[float]] = defaultdict(list)

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> tuple[str, LabelKey]:
        return name, tuple(sorted(labels.items()))

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self.counters[self._key(name, labels)] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self.observations[self._key(name, labels)].append(value)

    def get(self, name: str, **labels: str) -> float:
        """Sum of a counter over every series whose labels include ``labels``."""
        want = set(labels.items())
        with self._lock:
            return sum(v for (n, lk), v in self.counters.items() if n == name and want <= set(lk))

    def values(self, name: str, **labels: str) -> list[float]:
        want = set(labels.items())
        with self._lock:
            out: list[float] = []
            for (n, lk), vs in self.observations.items():
                if n == name and want <= set(lk):
                    out.extend(vs)
            return out


class NullMetrics:
    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        return None

    def observe(self, name: str, value: float, **labels: str) -> None:
        return None


# --- adapter to falcon_core.telemetry.metrics (builder-observability, PR #14) ------------------

TELEMETRY_MODULE = "falcon_core.telemetry.metrics"
# Our metric name -> attribute in the telemetry module.
_TELEMETRY_ATTRS: dict[str, str] = {
    LLM_TOKENS: "LLM_TOKENS",
    LLM_COST: "LLM_COST",
    LLM_FALLBACK: "LLM_FALLBACK",
    CANARY_LEAK: "CANARY_LEAK",
    ROUTE_AGREEMENT: "ROUTE_AGREEMENT",
    AGENT_STEPS: "AGENT_STEPS",
    TOOL_ERRORS: "TOOL_ERRORS",
    INJECTION_DETECTED: "INJECTION",
    LLM_CALLS: "LLM_CALLS",
    LLM_CALL_SECONDS: "LLM_CALL_SECONDS",
    LLM_RESULTS: "LLM_RESULTS",
    AGENT_TOOL_CALLS: "AGENT_TOOL_CALLS",
}
AGREEMENT_WINDOW = 200


class TelemetryMetrics:
    """``MetricsSink`` over the shared prometheus registry in ``falcon_core.telemetry.metrics``.

    Labels the shared metric does not declare are dropped (e.g. ``role`` on ``fl_canary_leak_total``),
    so a sink call never fails on a label mismatch; missing declared labels become "". The shared
    ``fl_route_agreement_ratio`` is a gauge, so observations set a rolling mean over the last
    ``AGREEMENT_WINDOW`` shadow samples. Unknown names are ignored.
    """

    def __init__(self, module: Any) -> None:
        self._metrics: dict[str, Any] = {
            name: getattr(module, attr) for name, attr in _TELEMETRY_ATTRS.items() if hasattr(module, attr)
        }
        self._agreement: deque[float] = deque(maxlen=AGREEMENT_WINDOW)
        self._lock = threading.Lock()

    def _bound(self, name: str, labels: dict[str, str]) -> Any | None:
        metric = self._metrics.get(name)
        if metric is None:
            return None
        names = tuple(getattr(metric, "_labelnames", ()))
        if not names:
            return metric
        return metric.labels(*(labels.get(n, "") for n in names))

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        bound = self._bound(name, labels)
        if bound is not None and value >= 0:
            bound.inc(value)

    def observe(self, name: str, value: float, **labels: str) -> None:
        bound = self._bound(name, labels)
        if bound is None:
            return
        if name == ROUTE_AGREEMENT:
            with self._lock:
                self._agreement.append(value)
                bound.set(sum(self._agreement) / len(self._agreement))
        else:
            bound.observe(value)


def default_metrics() -> MetricsSink:
    """The shared telemetry registry when it is installed, else an in-memory sink."""
    try:
        module = importlib.import_module(TELEMETRY_MODULE)
    except ImportError:
        return InMemoryMetrics()
    return TelemetryMetrics(module)
