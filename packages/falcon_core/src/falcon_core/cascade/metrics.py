"""``fl_`` metrics emitted by the cascade (names and labels from docs/OBSERVABILITY.md).

TODO(T-014): switch to the single registry in ``falcon_core.telemetry.metrics`` once
builder-observability merges it; until then each process passes its own ``CollectorRegistry``
(the service's ``app.state.registry``, so ``/metrics`` shows them).
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30)


class CascadeMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.checks = Counter(
            "fl_checks_total",
            "Checks completed (final verdicts)",
            ["input_type", "verdict", "tier", "route", "source"],
            registry=r,
        )
        self.stage_latency = Histogram(
            "fl_stage_latency_seconds",
            "Latency per cascade stage",
            ["stage"],
            buckets=_LATENCY_BUCKETS,
            registry=r,
        )
        self.escalations = Counter(
            "fl_escalations_total", "Cascade escalations", ["from", "to"], registry=r
        )
        self.cache_hits = Counter("fl_cache_hits_total", "Cache hits", ["layer"], registry=r)
        self.tool_errors = Counter(
            "fl_tool_errors_total", "Signal/tool errors", ["tool", "reason"], registry=r
        )
        self.sandbox_timeouts = Counter(
            "fl_sandbox_timeouts_total", "Sandbox render timeouts", registry=r
        )
        self.degraded = Counter("fl_degraded_total", "Degraded final verdicts", registry=r)
        self.ssrf_blocked = Counter(
            "fl_ssrf_blocked_total", "URLs blocked by the SSRF guard", ["reason"], registry=r
        )

    def on_ssrf_block(self, reason: object) -> None:
        """Hook for ``security.set_default_on_block`` (reason is a ``BlockReason``)."""
        self.ssrf_blocked.labels(str(getattr(reason, "value", reason))).inc()
