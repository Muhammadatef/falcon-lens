"""GET /v1/hunt/candidates, GET/PUT /v1/admin/hunt and Meta.hunt (T-035), against a fake Sentinel serving a mixed table."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import httpx
import pytest

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryAuditLog, MemoryKeyStore
from falcon_api.intel import SentinelClient
from tests.conftest import OPERATOR_KEY, SANDBOX_KEY, FakeStore, make_settings

T0 = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)
ULIDS = ["01JC8Z9Q3M5N7P2R4T6V8W0XY" + c for c in "ABCDEFG"]


def cand(i: int, status: str, domain: str, verdict: str | None = None, **kw: Any) -> dict[str, Any]:
    d = {
        "candidate_id": f"hc_{ULIDS[i]}",
        "domain_defanged": domain.replace(".", "[.]"),
        "domain_sha256": "a" * 64,
        "brand_id": "falcon_demo_bank",
        "discovery": "ct",
        "permutation_kind": None,
        "reasons": ["brand_token_in_cert", "cert_fresh"],
        "provenance": {
            "source_id": "fixture",
            "terms_url": None,
            "retrieved_at": "2026-11-24T20:00:00Z",
            "source": "fixture",
        },
        "first_seen": (T0 + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
        "upstream_seen": None,
        "prescore": 75,
        "status": status,
        "verdict_id": None,
        "verdict": verdict,
        "incident_id": None,
        "time_to_detection_s": None,
        "time_to_detection_basis": None,
    }
    d.update(kw)
    return d


ROWS = [
    cand(
        0,
        "confirmed",
        "falcon-demo-bank-secure.test",
        "dangerous",
        incident_id="inc_" + ULIDS[0],
        time_to_detection_s=60.0,
        time_to_detection_basis="cert_not_before",
        verdict_id="vd_" + ULIDS[0],
    ),
    cand(1, "cleared", "falcon-demo-bank-login.test", "no_warning_signs"),
    cand(2, "new", "falcon-demo-bank-pay.test"),
    cand(3, "submitted", "falcon-demo-bank-cloak.test"),
    cand(
        4, "confirmed", "falcon-demo-bank-fine.test", "suspicious", reasons=["<img src=x onerror=alert(1)>"]
    ),  # off-contract reason: must be dropped, never passed through
]
STATE = {
    "enabled": True,
    "paused": False,
    "interval_min": 15,
    "sources": [
        {"id": "permutation", "kind": "permutation", "status": "live", "terms_url": None},
        {"id": "fixture", "kind": "ct", "status": "live", "terms_url": None},
        {"id": "search", "kind": "search", "status": "ready_needs_key", "terms_url": None},
        {"id": "ads", "kind": "ads", "status": "ready_needs_key", "terms_url": None},
        {"id": "maps", "kind": "maps", "status": "ready_needs_key", "terms_url": None},
    ],
    "last_cycle_at": "2026-11-24T20:10:00Z",
    "last_cycle_outcome": "ok",
    "counts": {"confirmed": 2, "cleared": 1, "new": 1, "submitted": 1},
    "quota": {"per_hour": 20, "per_day": 200},
    "prescore_min": 60,
}


def sentinel_handler(req: httpx.Request) -> httpx.Response:
    assert req.headers.get("x-operator-key") == OPERATOR_KEY
    if req.url.path == "/internal/hunt":
        return httpx.Response(200, json=STATE)
    if req.url.path == "/internal/hunt/candidates":
        if req.url.params.get("view") == "operator":
            return httpx.Response(
                200,
                json={
                    "items": [{**r, "found_before_report": r["status"] == "confirmed"} for r in ROWS],
                    "counts": STATE["counts"],
                },
            )
        pub = []
        for r in ROWS:
            if r["status"] != "confirmed":
                continue
            pub.append(
                {
                    k: r[k]
                    for k in (
                        "candidate_id",
                        "domain_defanged",
                        "brand_id",
                        "discovery",
                        "permutation_kind",
                        "reasons",
                        "first_seen",
                        "verdict",
                        "incident_id",
                        "time_to_detection_s",
                        "time_to_detection_basis",
                    )
                }
                | {"found_before_report": r["incident_id"] is not None, "source": "fixture"}
            )
        return httpx.Response(200, json={"items": pub, "counts": STATE["counts"]})
    return httpx.Response(404)


@pytest.fixture
async def env() -> Any:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    keystore, audit = MemoryKeyStore(), MemoryAuditLog()
    read_key = (await Authenticator(keystore, "test-pepper").create("reader", ["read"], 100))[1]
    s = SentinelClient("http://sentinel", OPERATOR_KEY, transport=httpx.MockTransport(sentinel_handler))
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=100),
        redis=redis,
        store=FakeStore(),
        keystore=keystore,
        audit=audit,
        sentinel=s,
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, redis, audit, read_key


async def test_public_projection_confirmed_only_defanged(env: Any) -> None:
    c, _r, _a, read_key = env
    assert (await c.get("/v1/hunt/candidates")).status_code == 401
    assert (await c.get("/v1/hunt/candidates", headers={"X-API-Key": SANDBOX_KEY})).status_code == 403
    r = await c.get("/v1/hunt/candidates", headers={"X-API-Key": read_key})
    assert r.status_code == 200
    body = r.json()
    items = body["items"]
    assert [i["domain_defanged"] for i in items] == ["falcon-demo-bank-secure[.]test"]  # XSS row dropped
    raw = json.dumps(body)
    for live in (
        "falcon-demo-bank-secure.test",
        "falcon-demo-bank-pay",
        "falcon-demo-bank-cloak",
        "prescore",
        "onerror",
    ):
        assert live not in raw
    it = items[0]
    assert it["brand_name"] == {"ar": "بنك الصقر التجريبي", "en": "Falcon Demo Bank"}
    assert it["found_before_report"] is True and it["source"] == "fixture"
    assert it["time_to_detection_basis"] == "cert_not_before"
    assert body["counts"] == STATE["counts"]  # unconfirmed ones appear as counts only


async def test_admin_needs_operator_and_pause_is_audited(env: Any) -> None:
    c, redis, audit, read_key = env
    assert (await c.get("/v1/admin/hunt", headers={"X-API-Key": read_key})).status_code == 403
    assert (await c.put("/v1/admin/hunt", json={"paused": True}, headers={"X-API-Key": read_key})).status_code == 403
    assert not await redis.get("fl:hunt:paused")
    op = {"X-API-Key": OPERATOR_KEY}
    g = await c.get("/v1/admin/hunt", headers=op)
    assert g.status_code == 200 and len(g.json()["items"]) == len(ROWS) - 1  # off-contract row dropped
    assert "prescore" in g.json()["items"][0] and "onerror" not in g.text
    before = len(audit.rows)
    p = await c.put("/v1/admin/hunt", json={"paused": True}, headers=op)
    assert p.status_code == 200 and await redis.get("fl:hunt:paused")
    puts = [row for row in audit.rows[before:] if row["method"] == "PUT" and row["path"] == "/v1/admin/hunt"]
    assert len(puts) == 1 and puts[0]["note"] == "hunt paused False -> True"
    await c.put("/v1/admin/hunt", json={"paused": False}, headers=op)
    assert not await redis.get("fl:hunt:paused")
    assert (await c.put("/v1/admin/hunt", json={"paused": "yes", "x": 1}, headers=op)).status_code == 422


async def test_meta_hunt_block(env: Any) -> None:
    c, *_ = env
    hunt = (await c.get("/v1/meta")).json()["hunt"]
    assert hunt["enabled"] is True and hunt["interval_min"] == 15
    assert {s["id"]: s["status"] for s in hunt["sources"]}["maps"] == "ready_needs_key"
    assert set(hunt) == {"enabled", "paused", "interval_min", "sources", "last_cycle_at"}


async def test_meta_hunt_null_when_sentinel_down(store: FakeStore) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=req)

    s = SentinelClient("http://sentinel", OPERATOR_KEY, transport=httpx.MockTransport(boom))
    app = build_app(make_settings(), redis=fakeredis.FakeAsyncRedis(decode_responses=True), store=store, sentinel=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/v1/meta")).json()["hunt"] is None
