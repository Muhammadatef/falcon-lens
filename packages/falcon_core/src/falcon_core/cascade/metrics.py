"""``fl_`` metrics used by the cascade and worker.

By default these are the shared objects of ``falcon_core.telemetry.metrics`` (the single registry
that ``falcon_core.service`` renders on /metrics). Tests pass their own ``CollectorRegistry`` to get
isolated copies with the same names and labels.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

from falcon_core.telemetry import metrics as tm


def metric_source(source: str) -> str:
    """``fl_checks_total{source}`` is live|replay: replayed, synthetic and fixture data -> replay."""
    return "live" if source == "live" else "replay"


class CascadeMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        if registry is None:
            self.registry = tm.REGISTRY
            self.checks = tm.CHECKS
            self.stage_latency = tm.STAGE_LATENCY
            self.escalations = tm.ESCALATIONS
            self.cache_hits = tm.CACHE_HITS
            self.tool_errors = tm.TOOL_ERRORS
            self.sandbox_timeouts = tm.SANDBOX_TIMEOUTS
            self.degraded = tm.DEGRADED
            self.ssrf_blocked = tm.SSRF_BLOCKED
            self.hard_rules = tm.HARD_RULE_FIRED
            self.evidence = tm.EVIDENCE_SEEN
            self.sandbox_renders = tm.SANDBOX_RENDERS
            self.degraded_reasons = tm.DEGRADED_REASONS
            return
        r = self.registry = registry
        self.checks = Counter(
            "fl_checks_total",
            "Checks completed",
            ["input_type", "verdict", "tier", "route", "source"],
            registry=r,
        )
        self.stage_latency = Histogram(
            "fl_stage_latency_seconds",
            "Latency per pipeline stage",
            ["stage"],
            buckets=tm.STAGE_LATENCY_BUCKETS,
            registry=r,
        )
        self.escalations = Counter("fl_escalations_total", "Tier escalations", ["from", "to"], registry=r)
        self.cache_hits = Counter("fl_cache_hits_total", "Cache hits", ["layer"], registry=r)
        self.tool_errors = Counter("fl_tool_errors_total", "Tool/signal errors", ["tool", "reason"], registry=r)
        self.sandbox_timeouts = Counter("fl_sandbox_timeouts_total", "Sandbox timeouts", registry=r)
        self.degraded = Counter("fl_degraded_total", "Degraded verdicts", registry=r)
        self.ssrf_blocked = Counter("fl_ssrf_blocked_total", "SSRF guard blocks", ["reason"], registry=r)
        self.hard_rules = Counter("fl_hard_rule_fired_total", "Hard rules fired", ["rule", "effect"], registry=r)
        self.evidence = Counter("fl_evidence_total", "Evidence items on final verdicts", ["signal"], registry=r)
        self.sandbox_renders = Counter("fl_sandbox_renders_total", "Sandbox renders", ["outcome"], registry=r)
        self.degraded_reasons = Counter("fl_degraded_reasons_total", "Degraded reasons", ["reason"], registry=r)

    def record_result(self, result: object) -> None:
        """Hard-rule firings and the evidence signals behind one final verdict (an ``ArbiterResult``)."""
        for fired in getattr(result, "fired_rules", ()):
            self.hard_rules.labels(str(fired.rule_id), str(fired.effect)).inc()
        for reason in dict.fromkeys(getattr(result, "degraded_reasons", ())):
            self.degraded_reasons.labels(str(reason)[:60]).inc()
        for sig in {e.signal for e in getattr(result, "weighted_evidence", ())}:
            self.evidence.labels(sig[:64]).inc()

    def record_final(
        self, input_type: str, verdict: str, tier: str, route: str, source: str, latency_s: float | None = None
    ) -> None:
        """Count one finished check; ``latency_s`` feeds ``fl_stage_latency_seconds{stage="total"}``, the SLO stage."""
        self.checks.labels(input_type, verdict, tier, route, metric_source(source)).inc()
        if latency_s is not None:
            self.stage_latency.labels("total").observe(latency_s)

    def on_ssrf_block(self, reason: object) -> None:
        """Hook for ``security.set_default_on_block`` (reason is a ``BlockReason``)."""
        self.ssrf_blocked.labels(str(getattr(reason, "value", reason))).inc()
