"""Verdict model — mirrors contracts/verdict.schema.json."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from falcon_core.contracts.evidence import Evidence, Tier

Source = Literal["live", "replay", "synthetic", "fixture"]
ModelRoute = Literal["cloud", "local", "none"]
Channel = Literal["web", "extension", "api", "mcp", "voice", "hunt"]


class Brand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_id: str
    name_ar: str
    name_en: str
    official_domains: list[str] | None = None


class Reason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str = Field(max_length=220)
    en: str = Field(max_length=220)
    evidence_ids: list[str] = Field(min_length=1)
    generated_by: Literal["llm", "template"] | None = None


class BilingualList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: list[str] = Field(max_length=6)
    en: list[str] = Field(max_length=6)


class ReportChannel(BaseModel):
    label_ar: str
    label_en: str
    value: str
    source_url: str
    retrieved_at: date


class ReportAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str
    en: str
    channels: list[ReportChannel] | None = None


class Actions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: BilingualList
    if_already_acted: BilingualList
    report: ReportAction
    caution: BilingualList | None = None


class TraceStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int
    kind: Literal["tier", "tool", "llm", "rule"]
    name: str | None = None
    summary: str = Field(max_length=240)
    evidence_added: list[str] | None = None
    ms: int | None = None


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    verdict_id: str = Field(pattern=r"^vd_[0-9A-HJKMNP-TV-Z]{26}$")
    input_type: Literal["url", "message", "email", "image"]
    input_fingerprint: str | None = None
    canonical_url: str | None = None
    verdict: Literal["dangerous", "suspicious", "no_warning_signs"]
    risk_score: int = Field(ge=0, le=100)
    calibrated_probability: float = Field(ge=0, le=1)
    impersonated_brand: Brand | None = None
    evidence: list[Evidence]
    reasons: list[Reason] = Field(max_length=3)
    actions: Actions
    tier_reached: Tier
    model_route: ModelRoute
    degraded: bool
    degraded_reasons: list[str] | None = None
    final: bool
    trace: list[TraceStep] | None = None
    screenshot_url: str | None = None
    source: Source = "live"
    channel: Channel | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    latency_ms: int = Field(ge=0)
    created_at: datetime
