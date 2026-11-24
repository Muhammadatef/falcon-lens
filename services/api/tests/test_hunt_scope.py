"""Hunt scope (docs/design/HUNTER.md section 3): channel=hunt only from a `hunt` key; hunt checks stay out of history."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryKeyStore
from tests.conftest import OPERATOR_KEY, SANDBOX_KEY, FakeStore, make_doc, make_settings

URL = "http://falcon-demo-bank-secure.test/"
HUNT_KEY = "test-hunt-key"  # placeholder, not a credential


@pytest.fixture
async def hunt_client(redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FL_HUNT_API_KEY", HUNT_KEY)
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store, keystore=MemoryKeyStore()
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_channel_hunt_rejected_without_hunt_scope(hunt_client: httpx.AsyncClient) -> None:
    r = await hunt_client.post(
        "/v1/check/url", json={"url": URL, "channel": "hunt"}, headers={"X-API-Key": SANDBOX_KEY}
    )
    assert r.status_code == 422
    r = await hunt_client.post("/v1/check/url", json={"url": URL, "channel": "hunt"})  # anonymous
    assert r.status_code == 422


async def test_hunt_key_submits_only_as_hunt(hunt_client: httpx.AsyncClient, redis: Any) -> None:
    h = {"X-API-Key": HUNT_KEY}
    ok = await hunt_client.post("/v1/check/url", json={"url": URL, "channel": "hunt"}, headers=h)
    assert ok.status_code == 202 and ok.headers["x-verdict-state"] == "queued"
    job = (await redis.xrange("fl:jobs"))[-1][1]
    assert job["channel"] == "hunt" and job["source"] == "live"
    assert (await hunt_client.post("/v1/check/url", json={"url": URL + "x"}, headers=h)).status_code == 422
    for body in ({"text": "hello", "channel": "hunt"}, {"text": "hello"}):
        assert (await hunt_client.post("/v1/check/message", json=body, headers=h)).status_code == 403
    for path in ("/v1/verdicts", "/v1/incidents", "/v1/campaigns", "/v1/hunt/candidates", "/v1/admin/hunt"):
        assert (await hunt_client.get(path, headers=h)).status_code == 403, path  # hunt-only key: no read scope


async def test_hunt_fixture_source_label_kept(hunt_client: httpx.AsyncClient, redis: Any) -> None:
    h = {"X-API-Key": HUNT_KEY, "X-Falcon-Source": "fixture"}
    r = await hunt_client.post("/v1/check/url", json={"url": URL, "channel": "hunt"}, headers=h)
    assert r.status_code == 202
    assert (await redis.xrange("fl:jobs"))[-1][1]["source"] == "fixture"


def _event(verdict_id: str, channel: str | None) -> dict[str, str]:
    payload: dict[str, Any] = {"verdict": "dangerous", "input_type": "url", "risk_score": 90}
    if channel:
        payload["channel"] = channel
    ev = {
        "schema_version": "1.0",
        "event_id": "evt_" + verdict_id[3:],
        "type": "verdict.created",
        "occurred_at": "2026-11-24T10:00:00Z",
        "source": "live",
        "verdict_id": verdict_id,
        "payload": payload,
    }
    return {"event": json.dumps(ev)}


async def test_hunt_checks_not_in_public_history(redis: Any, store: FakeStore) -> None:
    keystore = MemoryKeyStore()
    read_key = (await Authenticator(keystore, "test-pepper").create("reader", ["read"], 100))[1]
    for n, ch in ((1, None), (2, "hunt"), (3, "web")):
        vid = f"vd_{n:026d}"
        store.docs[vid] = {**make_doc(vid, final=True), **({"channel": ch} if ch else {})}
        await redis.xadd("fl:events", _event(vid, ch))
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store, keystore=keystore)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/verdicts", headers={"X-API-Key": read_key})
        assert r.status_code == 200
        ids = [i["verdict_id"] for i in r.json()["items"]]
        assert f"vd_{2:026d}" not in ids
        assert f"vd_{1:026d}" in ids and f"vd_{3:026d}" in ids
        r2 = await c.get("/v1/verdicts", headers={"X-API-Key": OPERATOR_KEY})
        assert f"vd_{2:026d}" not in [i["verdict_id"] for i in r2.json()["items"]]
