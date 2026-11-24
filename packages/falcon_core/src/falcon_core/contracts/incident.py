"""Incident model — mirrors contracts/incident.schema.json.

The JSON Schema only sets ``additionalProperties: false`` on the root object, so the
nested models are intentionally permissive (pydantic default ``extra="ignore"``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from falcon_core.contracts.verdict import Channel, ModelRoute, Source


class SeverityReason(BaseModel):
    ar: str | None = None
    en: str | None = None
    evidence_ids: list[str] | None = None


class Indicator(BaseModel):
    kind: Literal["domain", "url", "ip", "dom_hash", "favicon_hash", "phone", "script_cluster"]
    value_defanged: str
    sha256: str | None = None
    first_seen: datetime
    blocked_until: datetime | None = None


class TimelineEntry(BaseModel):
    at: datetime
    what: str
    what_ar: str | None = None
    what_en: str | None = None
    event_id: str | None = None


class Claim(BaseModel):
    text_en: str
    evidence_ids: list[str] = Field(min_length=1)


class IncidentSummary(BaseModel):
    ar: str | None = None
    en: str | None = None
    claims: list[Claim] | None = None
    generated_by: Literal["llm", "template"] | None = None
    model_route: ModelRoute | None = None


class IncidentAction(BaseModel):
    action_id: str = Field(pattern=r"^act_")
    tool: Literal[
        "requeue_check",
        "block_indicator",
        "unblock_indicator",
        "raise_alert",
        "update_campaign_board",
        "export_stix",
        "draft_takedown",
        "draft_police_report",
    ]
    mode: Literal["internal_auto", "external_draft"]
    status: Literal["proposed", "executed", "awaiting_approval", "approved", "rejected", "reverted", "failed"]
    args: dict[str, Any] | None = None
    draft: dict[str, Any] | None = None
    evidence_ids: list[str]
    approved_by: str | None = None
    at: datetime | None = None


class Incident(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(pattern=r"^inc_[0-9A-HJKMNP-TV-Z]{26}$")
    type: Literal["campaign", "kit_reuse", "report_burst", "reputation_flip", "quality"]
    severity: Literal["low", "medium", "high", "critical"]
    severity_reason: SeverityReason | None = None
    status: Literal["open", "triaging", "awaiting_approval", "mitigated", "closed", "false_positive"]
    brand_id: str | None = None
    rule_ids: list[str] = Field(min_length=1)
    correlation_keys: dict[str, Any] | None = None
    indicators: list[Indicator]
    linked_verdicts: list[str]
    timeline: list[TimelineEntry]
    summary: IncidentSummary | None = None
    actions: list[IncidentAction]
    source: Source
    channels: list[Channel] | None = None
    created_at: datetime
    updated_at: datetime
