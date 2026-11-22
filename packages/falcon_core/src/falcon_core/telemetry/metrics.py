"""Single registry of every ``fl_`` metric (contract: docs/OBSERVABILITY.md).

Services import these objects and helpers; they never declare their own ``fl_`` metrics.
``falcon_core.service`` renders ``REGISTRY`` on /metrics next to the service's own registry.
"""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any, Literal, ParamSpec, TypeVar

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

Source = Literal["live", "replay"]

REGISTRY = CollectorRegistry()

# 10 ms .. 20 s: T0 lookups take tens of ms, the sandbox ~6 s, the end-to-end SLO is 8 s.
STAGE_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 20.0)
AGENT_STEP_BUCKETS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0)
TIME_TO_INCIDENT_BUCKETS = (1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0)


def _c(name: str, doc: str, labels: tuple[str, ...] = ()) -> Counter:
    return Counter(f"fl_{name}", doc, labels, registry=REGISTRY)


def _g(name: str, doc: str, labels: tuple[str, ...] = ()) -> Gauge:
    return Gauge(f"fl_{name}", doc, labels, registry=REGISTRY)


def _h(name: str, doc: str, buckets: tuple[float, ...], labels: tuple[str, ...] = ()) -> Histogram:
    return Histogram(f"fl_{name}", doc, labels, buckets=buckets, registry=REGISTRY)


# Checks
CHECKS = _c(
    "checks_total", "Checks completed", ("input_type", "verdict", "tier", "route", "source")
)
STAGE_LATENCY = _h(
    "stage_latency_seconds", "Latency per pipeline stage", STAGE_LATENCY_BUCKETS, ("stage",)
)
ESCALATIONS = _c("escalations_total", "Tier escalations", ("from", "to"))
CACHE_HITS = _c("cache_hits_total", "Cache hits", ("layer",))
# Health
TOOL_ERRORS = _c("tool_errors_total", "Tool/signal errors", ("tool", "reason"))
SANDBOX_TIMEOUTS = _c("sandbox_timeouts_total", "Sandbox visits that timed out")
FEED_AGE = _g("feed_age_seconds", "Age of the last successful feed refresh", ("feed",))
FEED_ENABLED = _g("feed_enabled", "1 if the feed is enabled, else 0", ("feed",))
DEGRADED = _c("degraded_total", "Verdicts produced in degraded mode")
# LLM
LLM_TOKENS = _c("llm_tokens_total", "LLM tokens (input + output)", ("model", "role"))
LLM_COST = _c("llm_cost_usd_total", "LLM spend in USD", ("model",))
LLM_FALLBACK = _c("llm_fallback_total", "LLM calls that fell back to the local model", ("role",))
ROUTE_AGREEMENT = _g("route_agreement_ratio", "Share of checks where routes agree (rolling)")
AGENT_STEPS = _h("agent_steps", "Agent steps per run", AGENT_STEP_BUCKETS)
CANARY_LEAK = _c("canary_leak_total", "Canary token seen in model output")
# Security
INJECTION = _c("injection_detected_total", "Prompt-injection attempts detected")
SSRF_BLOCKED = _c("ssrf_blocked_total", "Requests blocked by the SSRF guard", ("reason",))
RATE_LIMITED = _c("rate_limited_total", "Requests rejected by rate limits", ("scope",))
AUTH_FAILURES = _c("auth_failures_total", "Failed authentications")
# Brands and feedback
CAMPAIGN_NEW_DOMAINS = _c(
    "campaign_new_domains_total", "New domains attributed to a brand campaign", ("brand", "source")
)
BRAND_IMPERSONATION = _c("brand_impersonation_total", "Brand impersonation hits", ("brand",))
USER_FEEDBACK = _c("user_feedback_total", "User feedback submissions", ("type",))
# Evals
EVAL_METRIC = _g("eval_metric", "Metric from the latest eval artifact", ("name", "split", "route"))
SCORE_DRIFT = _g("score_drift_index", "Score distribution drift vs. baseline")
# Sentinel
INCIDENTS = _c("incidents_total", "Incidents opened", ("type", "severity", "source"))
INCIDENT_OPEN = _g("incident_open", "Open incidents", ("severity",))
RULE_FIRED = _c("rule_fired_total", "Sentinel rule firings", ("rule",))
TIME_TO_INCIDENT = _h(
    "time_to_incident_seconds", "First event to incident", TIME_TO_INCIDENT_BUCKETS
)
SENTINEL_ACTIONS = _c("sentinel_actions_total", "Sentinel actions", ("action", "mode"))
APPROVALS_PENDING = _g("approvals_pending", "External drafts waiting for approval")
BLOCKS_REVERTED = _c("blocks_reverted_total", "Blocks reverted")
EVENT_LAG = _g("event_lag_seconds", "Age of the oldest unprocessed bus event")
SENTINEL_DLQ = _c("sentinel_dead_letter_total", "Events moved to the dead-letter stream")

P = ParamSpec("P")
R = TypeVar("R")


class timed_stage:  # noqa: N801 - used like a function: context manager and decorator
    """Observe a stage's wall time in ``fl_stage_latency_seconds{stage}``.

    ``with timed_stage("t0"): ...`` or ``@timed_stage("t0")`` (sync or async).
    Failures are timed too, so slow errors stay visible.
    """

    def __init__(self, stage: str) -> None:
        self.stage = stage
        self._start = 0.0

    def __enter__(self) -> timed_stage:
        self._start = time.perf_counter()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        STAGE_LATENCY.labels(self.stage).observe(time.perf_counter() - self._start)

    def __call__(self, fn: Callable[P, R]) -> Callable[P, R]:
        stage = self.stage
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def awrapper(*args: Any, **kwargs: Any) -> Any:
                with timed_stage(stage):
                    return await fn(*args, **kwargs)

            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with timed_stage(stage):
                return fn(*args, **kwargs)

        return wrapper


def record_verdict(
    *,
    input_type: str,
    verdict: str,
    tier: str,
    route: str,
    source: Source = "live",
    degraded: bool = False,
) -> None:
    """Count one finished check (``source="replay"`` for replayed or synthetic data)."""
    if source not in ("live", "replay"):
        raise ValueError(f"source must be live|replay, got {source!r}")
    CHECKS.labels(input_type, verdict, tier, route, source).inc()
    if degraded:
        DEGRADED.inc()


def record_llm(
    *,
    model: str,
    role: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    fallback: bool = False,
) -> None:
    """Record one LLM call. The caller computes ``cost_usd`` from the price table."""
    LLM_TOKENS.labels(model, role).inc(max(input_tokens, 0) + max(output_tokens, 0))
    LLM_COST.labels(model).inc(max(cost_usd, 0.0))
    if fallback:
        LLM_FALLBACK.labels(role).inc()


def record_incident(*, type: str, severity: str, source: Source = "live") -> None:  # noqa: A002
    if source not in ("live", "replay"):
        raise ValueError(f"source must be live|replay, got {source!r}")
    INCIDENTS.labels(type, severity, source).inc()
