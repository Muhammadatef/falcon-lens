"""POST /v1/voice/utterance: scopes, caps, sniffing, engine routing, contract, privacy."""

from __future__ import annotations

import io
import json
import logging
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import jsonschema
import pytest

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryKeyStore
from falcon_api.voice import SttEngine, SttRouter, parse_engines, sniff, wav_seconds
from tests.conftest import SANDBOX_KEY, FakeStore, make_settings

SCHEMA = json.loads((Path(__file__).resolve().parents[3] / "contracts" / "voice.schema.json").read_text("utf-8"))
SECRET_WORDS = "very private spoken words"


def wav_bytes(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def stt_reply(text: str = "Hey Falcon, check this link", lang: str = "en") -> dict[str, Any]:
    return {"text": text, "lang": lang, "ms": 120, "duration_ms": 2000, "model": "whisper-large-v3-turbo"}


class Engines:
    """Fake STT engines keyed by host: a handler per engine."""

    def __init__(self, **handlers: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handlers = handlers
        self.calls: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        host = req.url.host
        self.calls.append(host)
        return self.handlers[host](req)


def ok(**kw: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _r: httpx.Response(200, json=stt_reply(**kw))


def boom(_r: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("down")


async def make_client(
    engines: Engines, spec: str = "native=http://nat,container=http://con"
) -> tuple[httpx.AsyncClient, str]:
    keystore = MemoryKeyStore()
    key = (await Authenticator(keystore, "test-pepper").create("web", ["read"], 1000))[1]
    router = SttRouter(parse_engines(spec), "tok", httpx.AsyncClient(transport=httpx.MockTransport(engines)))
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=1000),
        redis=fakeredis.FakeAsyncRedis(decode_responses=True),
        store=FakeStore(),
        keystore=keystore,
        stt_router=router,
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test"), key


def files(data: bytes, ctype: str = "audio/wav") -> dict[str, Any]:
    return {"audio": ("a.wav", data, ctype)}


async def test_happy_path_matches_contract() -> None:
    c, key = await make_client(Engines(nat=ok(), con=ok()))
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(2)), headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    jsonschema.validate(body, SCHEMA)
    assert body["wake"] is True
    assert body["intent"] == "check_clipboard"
    assert body["lang"] == "en"
    assert body["model"] == "native:whisper-large-v3-turbo"


async def test_owner_demo_line_and_arabic() -> None:
    en = "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens"
    c, key = await make_client(Engines(nat=ok(text=en), con=ok()))
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(3)), headers={"X-API-Key": key})
    assert (r.json()["wake"], r.json()["intent"]) == (True, "check_clipboard")
    ar = "يا فالكون، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر"
    c, key = await make_client(Engines(nat=ok(text=ar, lang="ar"), con=ok()))
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(3)), headers={"X-API-Key": key})
    assert (r.json()["lang"], r.json()["wake"], r.json()["intent"]) == ("ar", True, "check_clipboard")


async def test_scopes() -> None:
    c, key = await make_client(Engines(nat=ok(), con=ok()))
    async with c:
        assert (await c.post("/v1/voice/utterance", files=files(wav_bytes(1)))).status_code == 401
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": SANDBOX_KEY})
        assert r.status_code == 403  # check-only key lacks `read`
        assert (
            await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
        ).status_code == 200


async def test_size_and_duration_caps() -> None:
    c, key = await make_client(Engines(nat=ok(), con=ok()))
    h = {"X-API-Key": key}
    async with c:
        big = wav_bytes(40)  # 1.28 MB
        assert (await c.post("/v1/voice/utterance", files=files(big), headers=h)).status_code == 413
        long = wav_bytes(16, rate=8000)  # 16 s but under 1 MB
        r = await c.post("/v1/voice/utterance", files=files(long), headers=h)
        assert r.status_code == 422
        assert r.headers["content-type"].startswith("application/problem+json")
        assert (await c.post("/v1/voice/utterance", files=files(b""), headers=h)).status_code == 422


async def test_type_sniffing_and_lang_hint() -> None:
    c, key = await make_client(Engines(nat=ok(), con=ok()))
    h = {"X-API-Key": key}
    async with c:
        assert (await c.post("/v1/voice/utterance", files=files(b"MZ" + b"\x00" * 100), headers=h)).status_code == 415
        assert (
            await c.post("/v1/voice/utterance", files=files(wav_bytes(1), "audio/mpeg"), headers=h)
        ).status_code == 415
        # declared webm but the bytes are wav: refused
        assert (
            await c.post("/v1/voice/utterance", files=files(wav_bytes(1), "audio/webm"), headers=h)
        ).status_code == 415
        webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
        r = await c.post("/v1/voice/utterance", files=files(webm, "audio/webm;codecs=opus"), headers=h)
        assert r.status_code == 200
        bad = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), data={"lang_hint": "fr"}, headers=h)
        assert bad.status_code == 422
        good = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), data={"lang_hint": "ar"}, headers=h)
        assert good.status_code == 200


async def test_engine_rejection_maps_to_problem() -> None:
    long = httpx.Response(422, json={"error": "too_long"})
    c, key = await make_client(Engines(nat=lambda _r: long, con=ok()))
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
    assert r.status_code == 422
    assert "audio-too-long" in r.json()["type"]


async def test_falls_back_to_container_and_caches_health() -> None:
    eng = Engines(nat=boom, con=ok())
    c, key = await make_client(eng)
    async with c:
        for _ in range(3):
            r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
            assert r.status_code == 200
            assert r.json()["model"].startswith("container:")
    assert eng.calls == ["nat", "con", "con", "con"]  # native is tried once, then parked for a short while


async def test_engine_loading_503_falls_back_and_all_down_is_503() -> None:
    eng = Engines(nat=lambda _r: httpx.Response(503, json={"error": "model_unavailable"}), con=boom)
    c, key = await make_client(eng)
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
        assert r.status_code == 503
        assert "stt-unavailable" in r.json()["type"]
        m = (await c.get("/metrics")).text
        assert 'fl_voice_errors_total{reason="stt_unavailable"} 1.0' in m


async def test_rate_limit_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_VOICE_RATE_PER_MIN", "3")
    c, key = await make_client(Engines(nat=ok(), con=ok()))
    async with c:
        codes = [
            (await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})).status_code
            for _ in range(5)
        ]
    assert codes == [200, 200, 200, 429, 429]


async def test_privacy_no_transcript_in_logs_or_metrics(caplog: pytest.LogCaptureFixture) -> None:
    c, key = await make_client(Engines(nat=ok(text=f"Hey Falcon {SECRET_WORDS}"), con=ok()))
    caplog.set_level(logging.DEBUG)
    async with c:
        r = await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})
        assert SECRET_WORDS in r.json()["transcript"]
        metrics = (await c.get("/metrics")).text
    assert SECRET_WORDS not in metrics
    assert all(SECRET_WORDS not in str(rec.__dict__) for rec in caplog.records)
    assert 'fl_voice_utterances_total{engine="native",intent="none",lang="en",wake="true"} 1.0' in metrics
    assert "fl_voice_latency_seconds_bucket" in metrics


def test_helpers() -> None:
    assert sniff(wav_bytes(1)) == "wav"
    assert sniff(b"OggS" + b"\x00" * 10) == "ogg"
    assert sniff(b"nope") is None
    assert round(wav_seconds(wav_bytes(2.5)) or 0, 2) == 2.5
    names = [(e.name, e.url) for e in parse_engines("http://host.docker.internal:8093, http://voice:8000/")]
    assert names == [("native", "http://host.docker.internal:8093"), ("container", "http://voice:8000")]
    assert isinstance(SttEngine("x", "http://x").usable, bool)
