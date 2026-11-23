"""Sentinel metrics (docs/OBSERVABILITY.md, `fl_` prefix). Declared here until builder-observability's
falcon_core.telemetry.metrics lands; names and labels follow the doc exactly so the swap is mechanical."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

INCIDENTS_TOTAL = Counter("fl_incidents_total", "Incidents created", ["type", "severity", "source"])
INCIDENT_OPEN = Gauge("fl_incident_open", "Open incidents", ["severity"])
RULE_FIRED = Counter("fl_rule_fired_total", "Rule matches that created or changed an incident", ["rule"])
TIME_TO_INCIDENT = Histogram(
    "fl_time_to_incident_seconds",
    "Seconds from the triggering event to the incident (live source only)",
    buckets=(1, 5, 15, 30, 60, 120, 300, 900, 3600),
)
ACTIONS_TOTAL = Counter("fl_sentinel_actions_total", "Sentinel tool executions", ["action", "mode"])
APPROVALS_PENDING = Gauge("fl_approvals_pending", "External drafts awaiting operator approval")
BLOCKS_REVERTED = Counter("fl_blocks_reverted_total", "Blocks reverted by an operator")
EVENT_LAG = Gauge("fl_event_lag_seconds", "Age of the newest consumed stream entry")
DEAD_LETTER = Counter("fl_sentinel_dead_letter_total", "Events moved to fl:events:dlq")

SEVERITIES = ("low", "medium", "high", "critical")


class SentinelMetrics:
    """Implements falcon_core.tools.sentinel.MetricsPort plus consumer-side helpers."""

    def action(self, tool: str, mode: str) -> None:
        ACTIONS_TOTAL.labels(tool, mode).inc()

    def block_reverted(self) -> None:
        BLOCKS_REVERTED.inc()

    def refresh_gauges(self, incidents: Iterable[dict[str, Any]]) -> None:
        incs = list(incidents)
        for sev in SEVERITIES:
            INCIDENT_OPEN.labels(sev).set(
                sum(
                    1 for i in incs if i["severity"] == sev and i["status"] in ("open", "triaging", "awaiting_approval")
                )
            )
        APPROVALS_PENDING.set(sum(1 for i in incs for a in i["actions"] if a["status"] == "awaiting_approval"))


REQUEUE_FAILURES = Counter("fl_sentinel_requeue_failures_total", "Stuck-incident requeue failures")
