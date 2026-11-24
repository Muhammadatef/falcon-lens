"""HuntSource protocol and the Sighting record (HUNTER.md section 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol

SourceKind = Literal["ct", "permutation", "search", "ads", "maps"]
SourceStatus = Literal["live", "ready_needs_key", "disabled"]


class SourceDisabled(Exception):
    """The source is not usable (no key, terms unverified, or switched off)."""


class Paused(Exception):
    """The operator paused hunting (Redis fl:hunt:paused) or the kill switch is off: stop all outbound requests."""


@dataclass(frozen=True)
class Sighting:
    domain: str  # live A-label name (registrable or a host under it); never leaves the Sentinel
    brand_id: str
    discovery: SourceKind
    source_id: str
    terms_url: str | None
    retrieved_at: datetime
    source: Literal["live", "fixture", "replay"]
    permutation_kind: str | None = None
    reasons: tuple[str, ...] = ()
    upstream_seen: datetime | None = None
    # Fixture sightings only: the internal fixture host resolves on the sandbox network, never on public DNS.
    fixture_registered: bool = False
    scheme: Literal["https", "http"] = "https"
    extra: dict[str, str] = field(default_factory=dict)


class HuntSource(Protocol):
    id: str
    kind: SourceKind
    requires_key: bool
    terms_url: str | None

    def status(self) -> SourceStatus: ...

    async def poll(self, brands: list[str] | None, since: datetime | None) -> list[Sighting]: ...
