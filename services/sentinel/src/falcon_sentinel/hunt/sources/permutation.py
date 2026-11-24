"""Permutation source: brand look-alike names from sentinel_core.hunt.permute, served in batches with a cursor.

No network here; existence is checked afterwards through DoH (sources/dns.py). The cursor is persisted in
hunt_source_state so a restart continues where the last cycle stopped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sentinel_core.hunt.config import PermutationConfig
from sentinel_core.hunt.permute import Permutation, permute_registry

from falcon_core.signals.brands.registry import BrandRegistry

from ..clock import Clock
from .base import Sighting, SourceKind, SourceStatus


class PermutationSource:
    id = "permutation"
    kind: SourceKind = "permutation"
    requires_key = False
    terms_url: str | None = None

    def __init__(self, registry: BrandRegistry, cfg: PermutationConfig, clock: Clock, batch: int) -> None:
        self.registry, self.cfg, self.clock, self.batch = registry, cfg, clock, batch
        self.cursor: dict[str, Any] = {"offset": 0}
        self._all: list[Permutation] | None = None

    def status(self) -> SourceStatus:
        return "live"

    def names(self, brands: list[str] | None) -> list[Permutation]:
        if self._all is None:
            self._all = permute_registry(self.registry, self.cfg)
        out = self._all
        if brands:
            out = [p for p in out if p.brand_id in brands]
        # Demo brand names live on .test and never resolve publicly; they are covered by the fixture source.
        demo = {b.brand_id for b in self.registry.brands if b.is_demo}
        return [p for p in out if p.brand_id not in demo or (brands and p.brand_id in brands)]

    async def poll(self, brands: list[str] | None, since: datetime | None) -> list[Sighting]:
        names = self.names(brands)
        if not names or self.batch <= 0:
            return []
        start = int(self.cursor.get("offset", 0)) % len(names)
        take = [names[(start + i) % len(names)] for i in range(min(self.batch, len(names)))]
        self.cursor = {"offset": (start + len(take)) % len(names)}
        now = self.clock.now()
        return [
            Sighting(
                domain=p.name,
                brand_id=p.brand_id,
                discovery="permutation",
                source_id=self.id,
                terms_url=None,
                retrieved_at=now,
                source="live",
                permutation_kind=p.kind,
                reasons=(f"permutation:{p.kind}",),
            )
            for p in take
        ]
