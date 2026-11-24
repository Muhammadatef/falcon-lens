"""Public read-only history (read scope): GET /v1/verdicts and /v1/verdicts/stream (scopes, redaction, pagination, SSE)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from falcon_api import history
from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryKeyStore
from tests.conftest import OPERATOR_KEY, SANDBOX_KEY, FakeStore, make_doc, make_settings

OP = {"X-API-Key": OPERATOR_KEY}


def vid(n: int) -> str:
    return f"vd_{n:026d}"


def event(verdict_id: str, doc: dict[str, Any], typ: str = "verdict.created") -> dict[str, str]:
    ev = {
        "schema_version": "1.0",
        "event_id": "evt_" + verdict_id[3:],
        "type": typ,
        "occurred_at": "2026-11-24T10:00:00Z",
        "source": doc.get("source", "live"),
        "verdict_id": verdict_id,
        "payload": {"verdict": doc["verdict"], "input_type": doc["input_type"], "risk_score": doc["risk_score"]},
    }
    return {"event": json.dumps(ev)}


async def seed(redis: Any, store: FakeStore, n: int, **over: Any) -> str:
    doc = {**make_doc(vid(n), final=True), **over}
    store.docs[doc["verdict_id"]] = doc
    await redis.xadd("fl:events", event(doc["verdict_id"], doc))
    return str(doc["verdict_id"])


async def test_scopes(client: httpx.AsyncClient) -> None:
    for path in ("/v1/verdicts", "/v1/verdicts/stream"):
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers={"X-API-Key": SANDBOX_KEY})).status_code == 403


async def test_read_scope_can_list_and_stream_but_not_operate(
    redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner decision 24 Nov: history is public read-only until SSO. The web tier uses a `read` key, never `operator`."""
    monkeypatch.setattr(history, "STREAM_MAX_S", 0.5)
    keystore = MemoryKeyStore()
    read_key = (await Authenticator(keystore, "test-pepper").create("reader", ["read"], 100))[1]
    await seed(redis, store, 1)
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store, keystore=keystore)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/v1/verdicts", headers={"X-API-Key": read_key})
        assert r.status_code == 200 and [i["verdict_id"] for i in r.json()["items"]] == [vid(1)]
        # httpx's ASGI transport buffers a response, so the stream is bounded by STREAM_MAX_S (patched to 0.5 s).
        async with asyncio.timeout(4), c.stream(
            "GET", "/v1/verdicts/stream", headers={"X-API-Key": read_key, "Last-Event-ID": "0-0"}
        ) as s:
            assert s.status_code == 200
            lines = [line async for line in s.aiter_lines()]
        assert any(line.startswith("event: verdict") for line in lines)
        base = "/v1/incidents/inc_00000000000000000000000000/actions/act_x"
        for verb in ("approve", "reject"):
            assert (await c.post(f"{base}/{verb}", headers={"X-API-Key": read_key})).status_code == 403
        assert (await c.get("/v1/intel/stix", headers={"X-API-Key": read_key})).status_code == 403


async def test_redaction_no_userinfo_no_raw_text(client: httpx.AsyncClient, redis: Any, store: FakeStore) -> None:
    await seed(
        redis,
        store,
        1,
        canonical_url="hxxps://admin:hunter2@falcon-demo[.]test:8443/login?token=SECRET#x",
        evidence=[{"id": "ev_aaaaaaaa", "signal": "url.x", "source": "llm:extractor", "observed": "RAWBODY"}],
        reasons=[{"ar": "نص", "en": "REASON-TEXT", "evidence_ids": ["ev_aaaaaaaa"]}],
        degraded=True,
        degraded_reasons=["sandbox_timeout", "free text with spaces"],
        trace=[
            {"step": 1, "kind": "llm", "name": "investigator.plan", "summary": "x"},
            {"step": 2, "kind": "tool", "name": "whois", "summary": "y"},
        ],
        tier_reached="T3",
    )
    await seed(redis, store, 2, input_type="message", canonical_url="hxxp://leak[.]test/", text="my iban AE07...")
    r = await client.get("/v1/verdicts", headers=OP)
    assert r.status_code == 200
    for secret in ("hunter2", "admin", "SECRET", "login", "8443", "RAWBODY", "REASON-TEXT", "iban", "leak"):
        assert secret not in r.text
    rows = {i["verdict_id"]: i for i in r.json()["items"]}
    url_row, msg_row = rows[vid(1)], rows[vid(2)]
    assert url_row["display"] == "hxxps://falcon-demo[.]test"
    assert msg_row["display"] is None
    assert url_row["degraded_reasons"] == ["sandbox_timeout"]
    assert url_row["agent"] == {
        "tiers_run": ["T0", "T1", "T2", "T3"],
        "extractor_ran": True,
        "investigator_ran": True,
        "tool_calls": 1,
        "llm_calls": 1,
    }
    assert set(url_row) == {
        "verdict_id", "created_at", "input_type", "display", "verdict", "risk_score", "degraded",
        "degraded_reasons", "tier_reached", "model_route", "source", "agent",
    }  # fmt: skip


def test_defanged_host_edge_cases() -> None:
    assert history.defanged_host("hxxp://u:p@1[.]2[.]3[.]4/x") == "hxxp://1[.]2[.]3[.]4"
    assert history.defanged_host("hxxp://[::1]/") is None
    assert history.defanged_host("javascript:alert(1)") is None
    assert history.defanged_host(None) is None
    assert history.defanged_host("hxxp://bad host/") is None


async def test_pagination_filters_and_dedupe(client: httpx.AsyncClient, redis: Any, store: FakeStore) -> None:
    for n in range(1, 6):
        await seed(redis, store, n, verdict="dangerous" if n % 2 else "suspicious")
    # a duplicate upgrade event for #5 and a non-verdict event must not appear twice / at all
    await redis.xadd("fl:events", event(vid(5), store.docs[vid(5)], "verdict.upgraded"))
    await redis.xadd("fl:events", {"event": json.dumps({"type": "feed.updated", "verdict_id": None})})
    first = (await client.get("/v1/verdicts?limit=2", headers=OP)).json()
    assert [i["verdict_id"] for i in first["items"]] == [vid(5), vid(4)]
    assert first["next_cursor"]
    second = (await client.get(f"/v1/verdicts?limit=2&cursor={first['next_cursor']}", headers=OP)).json()
    assert [i["verdict_id"] for i in second["items"]] == [vid(3), vid(2)]
    third = (await client.get(f"/v1/verdicts?limit=2&cursor={second['next_cursor']}", headers=OP)).json()
    assert [i["verdict_id"] for i in third["items"]] == [vid(1)] and third["next_cursor"] is None
    only = (await client.get("/v1/verdicts?verdict=suspicious", headers=OP)).json()
    assert [i["verdict_id"] for i in only["items"]] == [vid(4), vid(2)]
    assert (await client.get("/v1/verdicts?input_type=email", headers=OP)).json()["items"] == []
    assert (await client.get("/v1/verdicts?cursor=nope", headers=OP)).status_code == 422
    assert (await client.get("/v1/verdicts?limit=0", headers=OP)).status_code == 422
    assert (await client.get("/v1/verdicts?verdict=safe", headers=OP)).status_code == 422


async def test_stream_replays_and_cleans_up(
    client: httpx.AsyncClient, redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(history, "STREAM_MAX_S", 0.5)
    await seed(redis, store, 1)
    await seed(redis, store, 2, canonical_url="hxxp://u:p@x[.]test/secret")
    r = await client.get("/v1/verdicts/stream", headers={**OP, "Last-Event-ID": "0-0"}, timeout=10)
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text.count("event: verdict") == 2
    assert "secret" not in r.text and ":p@" not in r.text
    data = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
    assert [d["verdict_id"] for d in data] == [vid(1), vid(2)]
    assert "id: " in r.text
    slots = client._transport.app.state.stream_slots  # type: ignore[attr-defined]
    assert sum(len(v) for v in slots.values()) == 0  # released on end


async def test_per_ip_rate_limit(redis: Any, store: FakeStore) -> None:
    app = build_app(make_settings(), redis=redis, store=store)
    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        codes = [
            (await c.get("/v1/verdicts", headers={**OP, "X-Falcon-Client-IP": "198.51.100.7"})).status_code
            for _ in range(62)
        ]
        assert codes[0] == 200 and codes[-1] == 429
        other = await c.get("/v1/verdicts", headers={**OP, "X-Falcon-Client-IP": "198.51.100.8"})
        assert other.status_code == 200
