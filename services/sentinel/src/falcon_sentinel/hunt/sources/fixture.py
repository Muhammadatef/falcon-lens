"""Recorded CT-shaped fixture source (demo and CI). Every sighting carries ``source=fixture``.

Reads a JSON file shaped like crt.sh rows (services/sentinel/fixtures/hunt_ct_fixture.json, TEST FIXTURE,
falcon-demo-bank*.test only). No network. Names are matched to brands by their registry tokens (demo included);
the official domain itself is dropped like in every other source.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sentinel_core.hunt.candidates import registrable
from sentinel_core.hunt.tokens import brand_tokens, token_in_name

from falcon_core.signals.brands.registry import BrandRegistry

from ..clock import Clock
from .base import Sighting, SourceKind, SourceStatus

DEFAULT_FIXTURE = Path(
    os.environ.get("FL_HUNT_FIXTURE") or Path(__file__).resolve().parents[4] / "fixtures" / "hunt_ct_fixture.json"
)
FIXTURE_LABEL = "TEST FIXTURE, not a real site"
FIXTURE_SUFFIXES = (".test", ".example", ".invalid", ".localhost")


class FixtureSource:
    id = "fixture"
    kind: SourceKind = "ct"
    requires_key = False
    terms_url: str | None = None

    def __init__(
        self, registry: BrandRegistry, clock: Clock, path: Path | str | None = None, fresh_days: int = 7
    ) -> None:
        self.registry, self.clock = registry, clock
        self.path = Path(path) if path else DEFAULT_FIXTURE
        self.fresh_days = fresh_days

    def status(self) -> SourceStatus:
        return "live" if self.path.is_file() else "disabled"

    def _rows(self) -> list[dict[str, Any]]:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("label") != FIXTURE_LABEL:
            raise ValueError("hunt fixture must carry the TEST FIXTURE label")
        return [r for r in data.get("rows", []) if isinstance(r, dict)]

    async def poll(self, brands: list[str] | None, since: datetime | None) -> list[Sighting]:
        now = self.clock.now()
        toks = [(b, t) for b, t in brand_tokens(self.registry, include_demo=True) if not brands or b in brands]
        out: dict[str, Sighting] = {}
        for r in self._rows():
            nb: datetime | None = None
            if isinstance(r.get("not_before_offset_s"), int):
                nb = now - timedelta(seconds=int(r["not_before_offset_s"]))
            for name in str(r.get("name_value", "")).splitlines():
                host = name.strip().lower().removeprefix("*.")
                reg = registrable(host)
                if not reg.endswith(FIXTURE_SUFFIXES) or self.registry.is_official(reg):
                    continue  # a fixture never names a real domain
                brand = next((b for b, t in toks if token_in_name(t, reg)), None)
                if brand is None:
                    continue
                reasons = ["brand_token_in_cert"]
                if nb is not None and now - nb < timedelta(days=self.fresh_days):
                    reasons.append("cert_fresh")
                prev = out.get(reg)
                if prev is None or (nb is not None and (prev.upstream_seen is None or nb < prev.upstream_seen)):
                    out[reg] = Sighting(
                        domain=reg,
                        brand_id=brand,
                        discovery="ct",
                        source_id=self.id,
                        terms_url=None,
                        retrieved_at=now,
                        source="fixture",
                        reasons=tuple(reasons),
                        upstream_seen=nb,
                        fixture_registered=True,
                        scheme="http",
                    )
        return list(out.values())
