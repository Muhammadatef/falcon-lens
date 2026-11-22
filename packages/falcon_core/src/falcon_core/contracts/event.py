"""PlatformEvent model — mirrors contracts/event.schema.json."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventType = Literal[
    "verdict.created",
    "verdict.upgraded",
    "report.submitted",
    "feedback.submitted",
    "feed.updated",
    "domain.observed",
    "incident.opened",
    "incident.updated",
    "action.executed",
    "action.requested",
]


class PlatformEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(pattern=r"^evt_[0-9A-HJKMNP-TV-Z]{26}$")
    type: EventType
    occurred_at: datetime
    source: Literal["live", "replay", "synthetic", "fixture"]
    verdict_id: str | None = None
    payload: dict[str, Any]
