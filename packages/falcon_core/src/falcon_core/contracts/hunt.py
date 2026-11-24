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
