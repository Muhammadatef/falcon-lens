"""Sentinel metrics (docs/OBSERVABILITY.md, `fl_` prefix). Declared here until builder-observability's
falcon_core.telemetry.metrics lands; names and labels follow the doc exactly so the swap is mechanical."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from falcon_core.telemetry import metrics as tm

# The contract metrics are the shared objects of falcon_core.telemetry.metrics: that registry (and not the
# prometheus_client default one) is what falcon_core.service renders on /metrics, so the Sentinel's incident,
# rule, action and lag series reach Prometheus. (They were declared on the default registry before and never
# exported.)
INCIDENTS_TOTAL = tm.INCIDENTS
INCIDENT_OPEN = tm.INCIDENT_OPEN
RULE_FIRED = tm.RULE_FIRED
TIME_TO_INCIDENT = tm.TIME_TO_INCIDENT
ACTIONS_TOTAL = tm.SENTINEL_ACTIONS
APPROVALS_PENDING = tm.APPROVALS_PENDING
BLOCKS_REVERTED = tm.BLOCKS_REVERTED
EVENT_LAG = tm.EVENT_LAG
DEAD_LETTER = tm.SENTINEL_DLQ

NODE_SECONDS = tm.SENTINEL_NODE_SECONDS
LLM_CALLS = tm.SENTINEL_LLM_CALLS
LLM_SECONDS = tm.SENTINEL_LLM_SECONDS
TEXT_SOURCE = tm.SENTINEL_TEXT
APPROVAL_TURNAROUND = tm.APPROVAL_TURNAROUND
INCIDENT_STATUS = tm.INCIDENT_STATUS
STATUSES = ("open", "triaging", "awaiting_approval", "mitigated", "closed")

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
        for st in STATUSES:
            INCIDENT_STATUS.labels(st).set(sum(1 for i in incs if i["status"] == st))
        APPROVALS_PENDING.set(sum(1 for i in incs for a in i["actions"] if a["status"] == "awaiting_approval"))


REQUEUE_FAILURES = tm.SENTINEL_REQUEUE_FAILURES
