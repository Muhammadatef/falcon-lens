"""Consumer side of the hunt: link verdict events to hunt candidates by verdict_id (HUNTER.md section 3).

The hunt_candidates table is the authority. ``payload.channel == "hunt"`` is only a metric label: a verdict is a
hunt verdict only when its verdict_id is stored on a candidate (which only the Sentinel's own submission does).
Incoming ``origin`` / ``hunt_*`` payload keys are always stripped first, so no producer can spoof them.

Sets on the stored event payload (it is the Sentinel's own feature record):
  origin = hunt | user, hunt_lookalike (bool), hunt_brand_id.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Any

from sentinel_core.correlate import refang
from sentinel_core.events import parse_time
from sentinel_core.hunt.candidates import Candidate, apply_verdict, registrable

from falcon_core.telemetry import metrics as tm

from .store import HuntStore

log = logging.getLogger("falcon.sentinel.hunt")
VERDICT_TYPES = ("verdict.created", "verdict.upgraded")
_INTERNAL_KEYS = ("origin", "hunt_lookalike", "hunt_brand_id")
_LOOKALIKE_DISCOVERY = ("permutation", "ct")  # names built from, or containing, a brand's registry label


def _ts(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v:
        return None
    try:
        return parse_time(v if "T" in v else v + "T00:00:00Z")
    except ValueError:
        return None


class HuntLinker:
    def __init__(self, store: HuntStore) -> None:
        self.store = store

    async def annotate(self, data: dict[str, Any]) -> Candidate | None:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            return None
        for k in _INTERNAL_KEYS:
            payload.pop(k, None)
        typ = data.get("type")
        if typ == "report.submitted":
            payload["origin"] = "user"
            return None
        if typ not in VERDICT_TYPES:
            return None
        vid = data.get("verdict_id")
        at = parse_time(str(data["occurred_at"]))
        c = await self.store.get_by_verdict(vid) if isinstance(vid, str) and vid else None
        if c is None:
            payload["origin"] = "user"
            if payload.get("channel") == "hunt":
                log.warning("hunt-channel verdict not in hunt_candidates; treated as a person's check")
            await self._lead(payload, at)
            return None
        payload["origin"] = "hunt"
        payload["hunt_lookalike"] = c.discovery in _LOOKALIKE_DISCOVERY
        payload["hunt_brand_id"] = c.brand_id
        verdict = payload.get("verdict")
        if c.status in ("submitted", "confirmed", "cleared") and isinstance(verdict, str):
            fp = payload.get("fingerprints") if isinstance(payload.get("fingerprints"), dict) else {}
            first = c.verdict is None
            new = apply_verdict(c, str(vid), verdict, at, _ts((fp or {}).get("registered_at")))
            await self.store.upsert(new)
            src = str(c.provenance.get("source", "live"))
            if first or new.verdict != c.verdict:
                tm.HUNT_CONFIRMED.labels(verdict, src).inc()
            if first and new.time_to_detection_s is not None and new.time_to_detection_basis:
                tm.HUNT_TIME_TO_DETECTION.labels(new.time_to_detection_basis, src).observe(new.time_to_detection_s)
            return new
        return c

    async def _lead(self, payload: dict[str, Any], at: datetime) -> None:
        """First person check of a domain the hunt already judged: observe the lead once."""
        dom = registrable(refang(str(payload.get("registrable_domain") or "")))
        if not dom:
            return
        hc = await self.store.get_by_domain(dom)
        if hc is None or hc.verdict_at is None or hc.first_user_seen is not None:
            return
        await self.store.upsert(replace(hc, first_user_seen=at))
        lead = (at - hc.verdict_at).total_seconds()
        if lead >= 0:
            tm.HUNT_LEAD.labels(str(hc.provenance.get("source", "live"))).observe(lead)

    async def link_incidents(self, incidents: list[dict[str, Any]]) -> None:
        """Store the incident id on every hunt candidate whose verdict an incident links."""
        for inc in incidents:
            for vid in inc.get("linked_verdicts", []):
                c = await self.store.get_by_verdict(vid)
                if c is not None and c.incident_id != inc["incident_id"]:
                    await self.store.upsert(replace(c, incident_id=inc["incident_id"]))
