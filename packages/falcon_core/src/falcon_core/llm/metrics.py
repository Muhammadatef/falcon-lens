"""Metric sink used by the router, tools and agents.

``docs/OBSERVABILITY.md`` says the ``fl_`` metrics are declared once in
``falcon_core/telemetry/metrics.py`` (builder-observability). Until it lands, this defines a
tiny sink protocol; the default in-memory sink keeps counts for tests and ``/metrics`` wiring can
adapt it later without touching callers. Metric names are the contract names.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Protocol

LLM_TOKENS = "fl_llm_tokens_total"  # {model, role}
LLM_COST = "fl_llm_cost_usd_total"  # {model}
LLM_FALLBACK = "fl_llm_fallback_total"  # {role}
CANARY_LEAK = "fl_canary_leak_total"  # {role}
ROUTE_AGREEMENT = "fl_route_agreement_ratio"  # observed per shadow sample {role}
AGENT_STEPS = "fl_agent_steps"  # histogram
TOOL_ERRORS = "fl_tool_errors_total"  # {tool, reason}
INJECTION_DETECTED = "fl_injection_detected_total"  # {source}

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
