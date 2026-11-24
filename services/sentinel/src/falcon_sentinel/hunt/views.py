"""Read views the API proxies (operator key on /internal/hunt*): state, public projection, operator projection.

Public projection (HUNTER.md section 6): only `confirmed` candidates, defanged names, no prescore, no live name;
every other status appears as a count only, so a legitimate owner's domain is never listed as suspected.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sentinel_core.hunt.candidates import Candidate, to_contract
from sentinel_core.hunt.config import HuntConfig

from .scheduler import PAUSE_KEY
from .settings import HuntSettings
from .store import HuntStore

KEYED_IDS = ("search", "ads", "maps")
SOURCE_ORDER = ("permutation", "ct_lookup", "ct_search", "fixture", "search", "ads", "maps")


def _iso(d: Any) -> str | None:
    if isinstance(d, datetime):
        return d.isoformat().replace("+00:00", "Z")
    return str(d) if d else None


def sources_view(settings: HuntSettings, cfg: HuntConfig) -> list[dict[str, Any]]:
    active = set(settings.active_sources()) if settings.enabled else set()
    out = []
    for sid in SOURCE_ORDER:
        spec = cfg.sources.get(sid)
        if spec is None:
            continue
        if sid in KEYED_IDS:
            status = "ready_needs_key"
        elif sid in active:
            status = "live"
        else:
            status = "disabled"
        out.append({"id": sid, "kind": spec.kind, "status": status, "terms_url": spec.terms_url})
    return out


async def state_view(settings: HuntSettings, cfg: HuntConfig, store: HuntStore | None, redis: Any) -> dict[str, Any]:
    paused = False
    if redis is not None:
        try:
            paused = bool(await redis.get(PAUSE_KEY))
        except Exception:  # noqa: BLE001 - unknown pause state is reported as not paused, the cycle re-checks
            paused = False
    last = await store.last_cycle() if store is not None else None
    counts = await store.counts() if store is not None else {}
    return {
        "enabled": settings.enabled,
        "paused": paused,
        "interval_min": settings.interval_min,
        "sources": sources_view(settings, cfg),
        "last_cycle_at": _iso((last or {}).get("finished_at") or (last or {}).get("started_at")),
        "last_cycle_outcome": (last or {}).get("outcome"),
        "counts": counts,
        "quota": {"per_hour": settings.submit_max_per_hour, "per_day": settings.submit_max_per_day},
        "prescore_min": settings.prescore_min,
    }


def _found_before_report(c: Candidate, incidents: dict[str, dict[str, Any]]) -> bool:
    inc = incidents.get(c.incident_id or "")
    det = (inc or {}).get("detection") or {}
    return det.get("found_before_report") is True and c.status == "confirmed"


def public_item(c: Candidate, incidents: dict[str, dict[str, Any]]) -> dict[str, Any]:
    d = to_contract(c)
    return {
        "candidate_id": d["candidate_id"],
        "domain_defanged": d["domain_defanged"],
        "brand_id": d["brand_id"],
        "discovery": d["discovery"],
        "permutation_kind": d["permutation_kind"],
        "reasons": d["reasons"],
        "first_seen": d["first_seen"],
        "verdict": d["verdict"],
        "incident_id": d["incident_id"],
        "found_before_report": _found_before_report(c, incidents),
        "time_to_detection_s": d["time_to_detection_s"],
        "time_to_detection_basis": d["time_to_detection_basis"],
        "source": d["provenance"]["source"],
    }


async def candidates_view(
    store: HuntStore, incidents: dict[str, dict[str, Any]], *, operator: bool, limit: int = 100
) -> dict[str, Any]:
    counts = await store.counts()
    if operator:
        rows = await store.list(None, limit=limit)
        items = [{**to_contract(c), "found_before_report": _found_before_report(c, incidents)} for c in rows]
    else:
        rows = await store.list(("confirmed",), limit=limit)
        items = [public_item(c, incidents) for c in rows]
        items.sort(key=lambda i: str(i["first_seen"]), reverse=True)
    return {"items": items, "counts": counts}
