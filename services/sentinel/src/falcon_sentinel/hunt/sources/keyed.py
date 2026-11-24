"""Search, ad-library and Maps-listing sources: interface and config only (HUNTER.md section 8).

No provider terms or API was verified for these, so there is deliberately no HTTP code here (a test asserts it).
``status()`` is ``ready_needs_key`` and ``poll()`` raises ``SourceDisabled``. Scraping result pages is out.
"""

from __future__ import annotations

from datetime import datetime

from .base import Sighting, SourceDisabled, SourceKind, SourceStatus


class _KeyedSource:
    id: str = ""
    kind: SourceKind = "search"
    requires_key = True
    terms_url: str | None = None

    def status(self) -> SourceStatus:
        return "ready_needs_key"

    async def poll(self, brands: list[str] | None, since: datetime | None) -> list[Sighting]:
        raise SourceDisabled(f"{self.id}: needs an API key and verified provider terms")


class SearchSource(_KeyedSource):
    id = "search"
    kind: SourceKind = "search"


class AdsLibrarySource(_KeyedSource):
    id = "ads"
    kind: SourceKind = "ads"


class MapsListingSource(_KeyedSource):
    id = "maps"
    kind: SourceKind = "maps"


KEYED = (SearchSource, AdsLibrarySource, MapsListingSource)
