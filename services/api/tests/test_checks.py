from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from falcon_api.app import build_app
from falcon_api.jobs import STREAM
from tests.conftest import SANDBOX_KEY, FakeStore, make_doc, make_settings, publish

PROBLEM = "application/problem+json"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
EML = b"From: a@example.test\r\nTo: b@example.test\r\nSubject: hi\r\n\r\nbody\r\n"


async def post_url(c: httpx.AsyncClient, url: str = "http://fixtures/a", **kw: Any) -> httpx.Response:
    return await c.post("/v1/check/url", json={"url": url}, **kw)


async def test_url_accepted_enqueues_job(client: httpx.AsyncClient, redis: Any) -> None:
    r = await post_url(client)
    assert r.status_code == 202
    body = r.json()
    vid = body["verdict_id"]
    assert body["events_url"] == f"/v1/verdicts/{vid}/events"
    assert body["status_url"] == f"/v1/verdicts/{vid}"
    assert r.headers["x-request-id"]
    entries = await redis.xrange(STREAM)
    assert len(entries) == 1
    fields = entries[0][1]
    assert set(fields) == {"verdict_id", "input_type", "payload_json", "submitted_at", "source"}
    assert fields["verdict_id"] == vid and fields["input_type"] == "url"
    assert json.loads(fields["payload_json"])["url"] == "http://fixtures/a"


async def test_single_flight_same_canonical_url(client: httpx.AsyncClient, redis: Any) -> None:
    rs = await asyncio.gather(post_url(client, "http://Fixtures/a#x"), post_url(client, "HTTP://fixtures:80/a"))
    assert rs[0].json()["verdict_id"] == rs[1].json()["verdict_id"]
    assert await redis.xlen(STREAM) == 1


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "ftp://x.test/", "http://", "a b"])
async def test_invalid_url_problem(client: httpx.AsyncClient, bad: str) -> None:
    r = await post_url(client, bad)
    assert r.status_code == 422
    assert r.headers["content-type"].startswith(PROBLEM)
    assert bad not in r.text  # never echo input


async def test_url_too_long_413(client: httpx.AsyncClient) -> None:
    r = await post_url(client, "http://x.test/" + "a" * 5000)
    assert r.status_code == 413
    assert r.headers["content-type"].startswith(PROBLEM)


async def test_missing_body_is_problem(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/check/url", json={})
    assert r.status_code == 422 and r.headers["content-type"].startswith(PROBLEM)
    assert r.json()["request_id"]


async def test_message_limit(client: httpx.AsyncClient) -> None:
    ok = await client.post("/v1/check/message", json={"text": "تم حظر حسابك"})
    assert ok.status_code == 202
    big = await client.post("/v1/check/message", json={"text": "a" * 8193})
    assert big.status_code == 413 and big.headers["content-type"].startswith(PROBLEM)


async def test_email_upload(client: httpx.AsyncClient, redis: Any) -> None:
    r = await client.post("/v1/check/email", files={"file": ("m.eml", EML, "message/rfc822")})
    assert r.status_code == 202
    vid = r.json()["verdict_id"]
    assert await redis.get(f"fl:blob:{vid}")
    bad = await client.post("/v1/check/email", files={"file": ("m.eml", b"\x00\x01bin", "x/y")})
    assert bad.status_code == 415
    wrong_ext = await client.post("/v1/check/email", files={"file": ("m.txt", EML, "text/plain")})
    assert wrong_ext.status_code == 415


async def test_email_size_cap(client: httpx.AsyncClient) -> None:
    big = EML + b"x" * (2 * 1024 * 1024)
    r = await client.post("/v1/check/email", files={"file": ("m.eml", big, "message/rfc822")})
    assert r.status_code == 413


async def test_image_magic(client: httpx.AsyncClient) -> None:
    ok = await client.post("/v1/check/image", files={"file": ("a.png", PNG, "image/png")})
    assert ok.status_code == 202
    bad = await client.post("/v1/check/image", files={"file": ("a.png", b"GIF89a" + b"0" * 20, "image/png")})
    assert bad.status_code == 415 and bad.headers["content-type"].startswith(PROBLEM)
    webp = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 8
    resp = await client.post("/v1/check/image", files={"file": ("a.webp", webp, "image/webp")})
    assert resp.status_code == 202


async def test_rate_limit_429(redis: Any, store: FakeStore) -> None:
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=3), redis=redis, store=store)
    t = httpx.ASGITransport(app=app, client=("198.51.100.7", 1))
    async with httpx.AsyncClient(transport=t, base_url="http://test") as c:
        codes = [(await post_url(c, f"http://x.test/{i}")).status_code for i in range(5)]
        assert codes == [202, 202, 202, 429, 429]
        r = await post_url(c)
        assert r.headers["content-type"].startswith(PROBLEM) and "retry-after" in r.headers
        m = await c.get("/metrics")
        assert 'fl_rate_limited_total{scope="ip"} 3.0' in m.text


async def test_idempotency(client: httpx.AsyncClient, redis: Any) -> None:
    h = {"Idempotency-Key": "abc-123"}
    a = await post_url(client, "http://x.test/1", headers=h)
    b = await post_url(client, "http://x.test/1", headers=h)
    assert a.json() == b.json() and b.headers["idempotent-replay"] == "true"
    assert await redis.xlen(STREAM) == 1
    c = await post_url(client, "http://x.test/2", headers=h)
    assert c.status_code == 422 and c.headers["content-type"].startswith(PROBLEM)
    d = await post_url(client, "http://x.test/2", headers={"Idempotency-Key": "bad key!"})
    assert d.status_code == 422


async def test_wait_returns_final_200(client: httpx.AsyncClient, redis: Any) -> None:
    async def worker() -> None:
        for _ in range(100):
            entries = await redis.xrange(STREAM)
            if entries:
                vid = entries[0][1]["verdict_id"]
                await publish(redis, make_doc(vid, final=False))
                await asyncio.sleep(0.3)
                await publish(redis, make_doc(vid, final=True))
                return
            await asyncio.sleep(0.02)

    task = asyncio.create_task(worker())
    r = await post_url(client, "http://x.test/w", params={"wait": 5})
    await task
    assert r.status_code == 200
    assert r.json()["final"] is True and r.json()["screenshot_url"] is None


async def test_wait_timeout_returns_partial_202(client: httpx.AsyncClient, redis: Any) -> None:
    async def worker() -> None:
        await asyncio.sleep(0.2)
        entries = await redis.xrange(STREAM)
        await publish(redis, make_doc(entries[0][1]["verdict_id"], final=False))

    task = asyncio.create_task(worker())
    r = await post_url(client, "http://x.test/p", params={"wait": 1.2})
    await task
    assert r.status_code == 202 and r.json()["final"] is False


async def test_wait_no_progress_returns_accepted(client: httpx.AsyncClient) -> None:
    r = await post_url(client, "http://x.test/n", params={"wait": 0.5})
    assert r.status_code == 202 and "events_url" in r.json()


async def test_cached_final_returns_200(client: httpx.AsyncClient, redis: Any, store: FakeStore) -> None:
    first = await post_url(client, "http://x.test/c")
    vid = first.json()["verdict_id"]
    store.docs[vid] = make_doc(vid, final=True, verdict="dangerous")
    assert (await client.get(f"/v1/verdicts/{vid}")).status_code == 200  # also fills vc:
    again = await post_url(client, "http://x.test/c")
    assert again.status_code == 200 and again.json()["verdict_id"] == vid
    assert again.headers["x-verdict-state"] == "cached"
    assert await redis.xlen(STREAM) == 1


async def test_get_verdict(client: httpx.AsyncClient, store: FakeStore) -> None:
    vid = "vd_" + "0" * 26
    nf = await client.get(f"/v1/verdicts/{vid}")
    assert nf.status_code == 404 and nf.headers["content-type"].startswith(PROBLEM)
    store.docs[vid] = make_doc(vid, final=True)
    anon = await client.get(f"/v1/verdicts/{vid}")
    assert anon.status_code == 200 and anon.json()["screenshot_url"] is None
    authed = await client.get(f"/v1/verdicts/{vid}", headers={"X-API-Key": SANDBOX_KEY})
    assert authed.json()["screenshot_url"] == "http://internal/shot.png"
    wrong = await client.get(f"/v1/verdicts/{vid}", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401 and wrong.headers["content-type"].startswith(PROBLEM)
    assert (await client.get("/v1/verdicts/not-an-id")).status_code == 422


async def test_sse_replay_then_final(client: httpx.AsyncClient, redis: Any) -> None:
    vid = (await post_url(client, "http://x.test/s")).json()["verdict_id"]
    await publish(redis, make_doc(vid, final=False))  # replayed from last-known

    async def finish() -> None:
        await asyncio.sleep(0.5)
        await publish(redis, make_doc(vid, final=True))

    task = asyncio.create_task(finish())
    r = await client.get(f"/v1/verdicts/{vid}/events", timeout=10)
    await task
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert [e["final"] for e in events] == [False, True]
    assert {e["verdict_id"] for e in events} == {vid}
    assert all(e["screenshot_url"] is None for e in events)
    assert "event: verdict" in r.text


async def test_sse_unknown_is_404_problem(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/verdicts/vd_" + "1" * 26 + "/events")
    assert r.status_code == 404 and r.headers["content-type"].startswith(PROBLEM)


async def test_cors_only_web_origin(client: httpx.AsyncClient) -> None:
    ok = await client.get("/v1/version", headers={"Origin": "https://app.example.test"})
    assert ok.headers["access-control-allow-origin"] == "https://app.example.test"
    bad = await client.get("/v1/version", headers={"Origin": "https://evil.test"})
    assert "access-control-allow-origin" not in bad.headers


async def test_404_is_problem(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/nope")
    assert r.status_code == 404 and r.headers["content-type"].startswith(PROBLEM)


async def test_content_length_required(client: httpx.AsyncClient) -> None:
    async def gen() -> AsyncIterator[bytes]:
        yield b'{"url": "http://x.test/"}'

    r = await client.post("/v1/check/url", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 411
