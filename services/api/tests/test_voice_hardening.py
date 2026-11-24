"""Voice route hardening: body cap before parsing, playlist-like payloads, fail-closed token."""

from __future__ import annotations

import fakeredis
import httpx

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryKeyStore
from falcon_api.voice import SttRouter, parse_engines
from tests.conftest import FakeStore, make_settings
from tests.test_voice import Engines, files, make_client, ok, wav_bytes


async def test_1_2_mb_body_is_refused_before_any_engine_call() -> None:
    eng = Engines(nat=ok(), con=ok())
    c, key = await make_client(eng)
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(37.5)), headers={"X-API-Key": key})
    assert r.status_code == 413
    assert eng.calls == []


async def test_playlist_like_payloads_are_never_forwarded() -> None:
    eng = Engines(nat=ok(), con=ok())
    c, key = await make_client(eng)
    h = {"X-API-Key": key}
    payloads = [
        b"ffconcat version 1.0\nfile '/etc/passwd'\n",
        b"#EXTM3U\n#EXT-X-VERSION:3\nhttp://169.254.169.254/\n",
        b"<?xml version='1.0'?><MPD></MPD>",
    ]
    async with c:
        for p in payloads:
            for ctype in ("audio/wav", "audio/webm", "audio/ogg"):
                r = await c.post("/v1/voice/utterance", files=files(p, ctype), headers=h)
                assert r.status_code == 415
    assert eng.calls == []


async def test_missing_token_fails_closed() -> None:
    keystore = MemoryKeyStore()
    key = (await Authenticator(keystore, "test-pepper").create("web", ["read"], 1000))[1]
    eng = Engines(nat=ok(), con=ok())
    router = SttRouter(parse_engines("native=http://nat"), "", httpx.AsyncClient(transport=httpx.MockTransport(eng)))
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=1000),
        redis=fakeredis.FakeAsyncRedis(decode_responses=True),
        store=FakeStore(),
        keystore=keystore,
        stt_router=router,
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
    assert r.status_code == 503
    assert eng.calls == []
