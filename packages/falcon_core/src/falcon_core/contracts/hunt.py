"""HuntCandidate model — mirrors contracts/hunt_candidate.schema.json (docs/design/HUNTER.md section 4).

The hunt finds, the arbiter decides. ``prescore`` is a queue priority, never a risk score.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Discovery = Literal["ct", "permutation", "search", "ads", "maps"]
PermutationKind = Literal["typo", "homoglyph", "combosquat", "tld_swap"]
CandidateStatus = Literal[
    "new",
    "unregistered",
    "queued",
    "submitted",
    "confirmed",
    "cleared",
    "already_known",
    "skipped_quota",
    "error",
]
REASON_PATTERN = (
    r"^(brand_token_in_cert|resolves_a|has_mx|cert_fresh|permutation:(typo|homoglyph|combosquat|tld_swap))$"
)


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    terms_url: str | None
    retrieved_at: datetime
    source: Literal["live", "fixture", "replay"]


class HuntCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^hc_[0-9A-HJKMNP-TV-Z]{26}$")
    domain_defanged: str = Field(pattern=r"^[^.]+(\[\.\][^.]+)+$")
    domain_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    brand_id: str
    discovery: Discovery
    permutation_kind: PermutationKind | None
    reasons: list[Annotated[str, Field(pattern=REASON_PATTERN)]]
    provenance: Provenance
    first_seen: datetime
    upstream_seen: datetime | None
    prescore: int = Field(ge=0, le=100)
    status: CandidateStatus
    verdict_id: str | None
    verdict: Literal["no_warning_signs", "suspicious", "dangerous"] | None
    incident_id: str | None
    time_to_detection_s: float | None = Field(ge=0)
    time_to_detection_basis: Literal["cert_not_before", "rdap"] | None = None


# ---- REST projections (GET /v1/hunt/candidates, GET/PUT /v1/admin/hunt, Meta.hunt); openapi.yaml is generated
# from the API models that use these. The public feed never carries prescore or a live name.

SourceStatus = Literal["live", "ready_needs_key", "disabled"]


class BrandName(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str
    en: str


class HuntSourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Discovery
    status: SourceStatus
    terms_url: str | None


class HuntMeta(BaseModel):
    """`hunt` block of GET /v1/meta: what the hunt mode is and is not doing right now (capability flag)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    paused: bool
    interval_min: int
    sources: list[HuntSourceInfo]
    last_cycle_at: datetime | None


class HuntFeedItem(BaseModel):
    """One arbiter-confirmed candidate, public projection (defanged; no prescore)."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(pattern=r"^hc_[0-9A-HJKMNP-TV-Z]{26}$")
    domain_defanged: str = Field(pattern=r"^[^.]+(\[\.\][^.]+)+$")
    brand_id: str
    brand_name: BrandName | None = None
    discovery: Discovery
    permutation_kind: PermutationKind | None
    reasons: list[Annotated[str, Field(pattern=REASON_PATTERN)]]
    first_seen: datetime
    verdict: Literal["suspicious", "dangerous"]
    incident_id: str | None
    found_before_report: bool
    time_to_detection_s: float | None = Field(ge=0)
    time_to_detection_basis: Literal["cert_not_before", "rdap"] | None
    source: Literal["live", "fixture", "replay"]


class HuntFeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HuntFeedItem]
    counts: dict[CandidateStatus, int] = Field(
        description="All candidates by status (unconfirmed ones appear only here)."
    )


class HuntAdminItem(HuntCandidate):
    """Operator view: the full contract record (defanged) plus the incident's found_before_report."""

    found_before_report: bool


class HuntAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    paused: bool
    interval_min: int
    sources: list[HuntSourceInfo]
    last_cycle_at: datetime | None
    last_cycle_outcome: str | None
    counts: dict[CandidateStatus, int]
    quota: dict[str, int]
    prescore_min: int
    items: list[HuntAdminItem]


class HuntAdminIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paused: bool = Field(description="true pauses every outbound hunt request within one request; false resumes.")
