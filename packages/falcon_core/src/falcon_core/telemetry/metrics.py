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
# Label values follow contracts/verdict.schema.json (tier_reached, model_route).
TIERS = ("T0", "T1", "T2", "T3")
ROUTES = ("cloud", "local", "none")

REGISTRY = CollectorRegistry()

# 10 ms .. 20 s: T0 lookups take tens of ms, the sandbox ~6 s, the end-to-end SLO is 8 s.
STAGE_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0, 12.0, 20.0)
AGENT_STEP_BUCKETS = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0)
LLM_CALL_BUCKETS = (0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 40.0)
TIME_TO_INCIDENT_BUCKETS = (1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0)


def _c(name: str, doc: str, labels: tuple[str, ...] = ()) -> Counter:
    return Counter(f"fl_{name}", doc, labels, registry=REGISTRY)


def _g(name: str, doc: str, labels: tuple[str, ...] = ()) -> Gauge:
    return Gauge(f"fl_{name}", doc, labels, registry=REGISTRY)


def _h(name: str, doc: str, buckets: tuple[float, ...], labels: tuple[str, ...] = ()) -> Histogram:
    return Histogram(f"fl_{name}", doc, labels, buckets=buckets, registry=REGISTRY)


# Checks
CHECKS = _c("checks_total", "Checks completed", ("input_type", "verdict", "tier", "route", "source"))
STAGE_LATENCY = _h("stage_latency_seconds", "Latency per pipeline stage", STAGE_LATENCY_BUCKETS, ("stage",))
ESCALATIONS = _c("escalations_total", "Tier escalations", ("from", "to"))
CACHE_HITS = _c("cache_hits_total", "Cache hits", ("layer",))
VOICE_CHECKS = _c(
    "voice_checks_total", "Final verdicts of checks started by the voice assistant (channel=voice)", ("verdict",)
)
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
# Per-call view of the LLM router (additive; the token/cost/fallback counters above stay as they were).
# outcome: ok | timeout | error | budget (one series per provider call, so a repaired call counts twice).
# fallback: "true" when the call ran because the cloud attempt of the same request failed.
LLM_CALLS = _c(
    "llm_calls_total", "Provider calls by role, route, outcome and fallback", ("role", "route", "outcome", "fallback")
)
LLM_CALL_SECONDS = _h("llm_call_seconds", "Provider call wall time", LLM_CALL_BUCKETS, ("role", "route"))
# status: ok | repaired | fallback (caller template used) | failed. One series per finished request.
LLM_RESULTS = _c("llm_results_total", "Finished LLM requests by role and result", ("role", "status"))
ROUTE_AGREEMENT = _g("route_agreement_ratio", "Share of checks where routes agree (rolling)")
# No shadow sample yet means "no measurement", not "0% agreement": a label-less gauge exports 0 from the start,
# which kept RouteAgreementDrop firing with FL_SHADOW_RATE=0. NaN compares false in PromQL and plots as no data.
ROUTE_AGREEMENT.set(float("nan"))
AGENT_STEPS = _h("agent_steps", "Agent steps per run", AGENT_STEP_BUCKETS)
CANARY_LEAK = _c("canary_leak_total", "Canary token seen in model output")
# Cascade detail (additive)
HARD_RULE_FIRED = _c("hard_rule_fired_total", "Hard rules that fired on a final verdict", ("rule", "effect"))
EVIDENCE_SEEN = _c("evidence_total", "Evidence items on final verdicts, by signal id", ("signal",))
# outcome: ok | partial (page rendered with an error note) | timeout | failed
SANDBOX_RENDERS = _c("sandbox_renders_total", "Sandbox render attempts by outcome", ("outcome",))
AGENT_TOOL_CALLS = _c("agent_tool_calls_total", "Investigator tool calls by tool and status", ("tool", "status"))
# state: pending (delivered, not yet acked) | lag (not yet delivered); set by the worker every reclaim cycle
QUEUE_DEPTH = _g("queue_depth", "Jobs in the check queue by state", ("stream", "state"))
DEGRADED_REASONS = _c("degraded_reasons_total", "Degraded final verdicts by reason", ("reason",))
# Sentinel detail (additive; dashboards "Sentinel" and "AI operations")
SENTINEL_BUCKETS = (0.01, 0.05, 0.25, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 120.0)
SENTINEL_NODE_SECONDS = _h("sentinel_node_seconds", "Triage graph node wall time", SENTINEL_BUCKETS, ("node",))
SENTINEL_LLM_CALLS = _c(
    "sentinel_llm_calls_total", "Sentinel LLM asks (outcome ok|timeout|budget|invalid)", ("task", "outcome")
)
SENTINEL_LLM_SECONDS = _h("sentinel_llm_seconds", "Sentinel LLM ask wall time", SENTINEL_BUCKETS, ("task",))
SENTINEL_TEXT = _c("sentinel_text_total", "Sentinel texts by generator (llm|template)", ("task", "generated_by"))
APPROVAL_TURNAROUND = _h(
    "approval_turnaround_seconds",
    "Seconds from an action proposal to the operator decision",
    (30.0, 120.0, 300.0, 900.0, 1800.0, 3600.0, 14400.0, 86400.0),
    ("decision",),
)
INCIDENT_STATUS = _g("incident_status", "Incidents by status", ("status",))
SENTINEL_REQUEUE_FAILURES = _c("sentinel_requeue_failures_total", "Stuck-incident requeue failures")
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
# surface: list (GET /v1/campaigns) | stream (GET /v1/campaigns/stream). One per request; no caller identity is kept.
CAMPAIGN_BOARD_VIEWS = _c("campaign_board_views_total", "Campaign board reads through the API", ("surface",))
# Evals
EVAL_METRIC = _g("eval_metric", "Metric from the latest eval artifact", ("name", "split", "route"))
SCORE_DRIFT = _g("score_drift_index", "Score distribution drift vs. baseline")
# Sentinel
INCIDENTS = _c("incidents_total", "Incidents opened", ("type", "severity", "source"))
INCIDENT_OPEN = _g("incident_open", "Open incidents", ("severity",))
RULE_FIRED = _c("rule_fired_total", "Sentinel rule firings", ("rule",))
TIME_TO_INCIDENT = _h("time_to_incident_seconds", "First event to incident", TIME_TO_INCIDENT_BUCKETS)
SENTINEL_ACTIONS = _c("sentinel_actions_total", "Sentinel actions", ("action", "mode"))
APPROVALS_PENDING = _g("approvals_pending", "External drafts waiting for approval")
BLOCKS_REVERTED = _c("blocks_reverted_total", "Blocks reverted")
EVENT_LAG = _g("event_lag_seconds", "Age of the oldest unprocessed bus event")
SENTINEL_DLQ = _c("sentinel_dead_letter_total", "Events moved to the dead-letter stream")

# Sentinel hunt mode (docs/design/HUNTER.md section 5). Every series carries `source` (live|fixture|replay) so
# fixture-fed demo hunting stays labelled. No domain name is ever a label.
HUNT_TTD_BUCKETS = (60.0, 300.0, 900.0, 3600.0, 6 * 3600.0, 86400.0, 3 * 86400.0, 7 * 86400.0, 30 * 86400.0)
HUNT_CYCLES = _c("hunt_cycles_total", "Hunt cycles by outcome", ("outcome", "source"))
HUNT_SOURCE_REQUESTS = _c(
    "hunt_source_requests_total", "Outbound hunt requests (DoH, crt.sh) by outcome", ("source_id", "outcome", "source")
)
HUNT_CANDIDATES = _c("hunt_candidates_total", "New hunt candidates recorded", ("discovery", "source"))
HUNT_SUBMITTED = _c("hunt_submitted_total", "Hunt candidates submitted to the Investigator", ("source",))
HUNT_CONFIRMED = _c("hunt_confirmed_total", "Hunt candidates the arbiter confirmed or cleared", ("verdict", "source"))
HUNT_ALREADY_KNOWN = _c("hunt_already_known_total", "Hunt candidates a person had already checked", ("source",))
HUNT_QUOTA_REMAINING = _g("hunt_quota_remaining", "Hunt submission quota left in the window", ("quota", "source"))
HUNT_ENABLED = _g("hunt_enabled", "1 if the hunt task runs (FL_HUNT_ENABLED), else 0", ("source",))
HUNT_LAST_SUCCESS = _g(
    "hunt_last_success_timestamp_seconds", "Unix time of the last successful poll per source", ("source_id", "source")
)
HUNT_TIME_TO_DETECTION = _h(
    "hunt_time_to_detection_seconds",
    "Arbiter verdict time minus the earliest upstream timestamp (cert not_before or RDAP registration)",
    HUNT_TTD_BUCKETS,
    ("basis", "source"),
)
HUNT_LEAD = _h(
    "hunt_lead_seconds", "First person check of a domain minus the hunt verdict time", HUNT_TTD_BUCKETS, ("source",)
)

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
    if tier not in TIERS:
        raise ValueError(f"tier must be one of {TIERS}, got {tier!r}")
    if route not in ROUTES:
        raise ValueError(f"route must be one of {ROUTES}, got {route!r}")
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


def record_campaign_board_view(surface: str) -> None:
    """Count one read of the public campaign board (``list`` or ``stream``)."""
    if surface not in ("list", "stream"):
        raise ValueError(f"surface must be list|stream, got {surface!r}")
    CAMPAIGN_BOARD_VIEWS.labels(surface).inc()


def record_incident(*, type: str, severity: str, source: Source = "live") -> None:  # noqa: A002
    if source not in ("live", "replay"):
        raise ValueError(f"source must be live|replay, got {source!r}")
    INCIDENTS.labels(type, severity, source).inc()
