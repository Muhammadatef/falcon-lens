"""Sentinel-side hunt views (T-035): public projection is confirmed-only, defanged, no prescore; state is truthful."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

from falcon_sentinel.hunt.settings import HuntSettings
from falcon_sentinel.hunt.store import MemoryHuntStore
from falcon_sentinel.hunt.views import candidates_view, sources_view, state_view
from sentinel_core.hunt.candidates import Candidate
from sentinel_core.hunt.config import default_config

T0 = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)


def c(domain: str, status: str, **kw: object) -> Candidate:
    base: dict[str, object] = {
        "domain": domain,
        "brand_id": "falcon_demo_bank",
        "discovery": "ct",
        "permutation_kind": None,
        "first_seen": T0,
        "provenance": {"source_id": "fixture", "terms_url": None, "retrieved_at": T0, "source": "fixture"},
        "reasons": ("brand_token_in_cert",),
        "prescore": 80,
        "status": status,
    }
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


async def test_public_view_mixed_table() -> None:
    store = MemoryHuntStore()
    inc = "inc_01JC8Z9Q3M5N7P2R4T6V8W0XYZ"
    for x in (
        c("falcon-demo-bank-secure.test", "confirmed", verdict="dangerous", verdict_id="vd_1", incident_id=inc),
        c("falcon-demo-bank-login.test", "cleared", verdict="no_warning_signs"),
        c("falcon-demo-bank-pay.test", "new"),
        c("falcon-demo-bank-fine.test", "already_known"),
    ):
        await store.upsert(x)
    incidents = {inc: {"incident_id": inc, "detection": {"found_before_report": True}}}
    pub = await candidates_view(store, incidents, operator=False)
    raw = json.dumps(pub)
    assert [i["domain_defanged"] for i in pub["items"]] == ["falcon-demo-bank-secure[.]test"]
    assert "prescore" not in raw and "falcon-demo-bank-pay" not in raw and ".test\"" not in raw
    assert pub["items"][0]["found_before_report"] is True
    assert pub["counts"] == {"confirmed": 1, "cleared": 1, "new": 1, "already_known": 1}
    op = await candidates_view(store, incidents, operator=True)
    assert len(op["items"]) == 4 and all("prescore" in i for i in op["items"])
    assert "falcon-demo-bank-pay.test" not in json.dumps(op)  # operator view is defanged too


def test_sources_view_truthful() -> None:
    cfg = default_config()
    off = {s["id"]: s["status"] for s in sources_view(HuntSettings(), cfg)}
    assert off["permutation"] == "disabled"  # FL_HUNT_ENABLED false: nothing is live
    assert off["search"] == off["ads"] == off["maps"] == "ready_needs_key"
    on = {s["id"]: s["status"] for s in sources_view(replace(HuntSettings(), enabled=True, sources=("permutation", "fixture")), cfg)}
    assert on["permutation"] == "live" and on["fixture"] == "live" and on["ct_lookup"] == "disabled"


async def test_state_view_paused_flag() -> None:
    import fakeredis

    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    s = await state_view(HuntSettings(), default_config(), MemoryHuntStore(), r)
    assert s["enabled"] is False and s["paused"] is False and s["last_cycle_at"] is None
    await r.set("fl:hunt:paused", "op")
    assert (await state_view(HuntSettings(), default_config(), MemoryHuntStore(), r))["paused"] is True
