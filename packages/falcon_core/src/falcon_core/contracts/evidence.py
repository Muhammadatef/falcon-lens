"""Evidence model — mirrors contracts/evidence.schema.json."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["T0", "T1", "T2", "T3"]
Family = Literal[
    "url",
    "domain",
    "reputation",
    "page",
    "visual",
    "brand",
    "message",
    "email",
    "image",
    "injection",
    "llm",
]


class EvidenceDisplay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str | None = Field(default=None, max_length=200)
    en: str | None = Field(default=None, max_length=200)


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^ev_[a-z0-9]{8,32}$")
    signal: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,63}$")
    family: Family
    observed: Any
    display: EvidenceDisplay | None = None
    weight: float = Field(ge=-100, le=100)
    polarity: Literal["risk", "trust", "neutral"] = "neutral"
    hard_rule: str | None = None
    source: str
    tier: Tier
    confidence: float = Field(default=1.0, ge=0, le=1)
    latency_ms: int | None = Field(default=None, ge=0)
    error: str | None = None
