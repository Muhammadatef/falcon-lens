"""Voice router hardening (audit 2026-11-24): per-engine time budgets, failover and gate metrics, 503 Retry-After."""

from __future__ import annotations

import httpx

from falcon_api.voice import DEFAULT_ENGINE_TIMEOUT_S, ENGINE_TIMEOUT_S
from tests.test_voice import Engines, boom, files, make_client, ok, stt_reply, wav_bytes


def slow(_r: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("engine hung")


async def post(c: httpx.AsyncClient, key: str) -> httpx.Response:
    return await c.post("/v1/voice/utterance", files=files(wav_bytes(1)), headers={"X-API-Key": key})


def test_engine_budgets_fit_inside_the_web_route_abort() -> None:
    assert sum(ENGINE_TIMEOUT_S.values()) < 20  # web/app/api/voice/route.ts aborts at 20 s
    assert ENGINE_TIMEOUT_S["native"] < ENGINE_TIMEOUT_S["container"] <= DEFAULT_ENGINE_TIMEOUT_S


async def test_each_engine_call_carries_its_own_budget() -> None:
    seen: dict[str, float | None] = {}

    def record(req: httpx.Request) -> httpx.Response:
        seen[req.url.host] = req.extensions["timeout"]["read"]
        return httpx.Response(503, json={"error": "model_unavailable"}) if req.url.host == "nat" else ok()(req)

    c, key = await make_client(Engines(nat=record, con=record))
    async with c:
        assert (await post(c, key)).status_code == 200
    assert seen == {"nat": ENGINE_TIMEOUT_S["native"], "con": ENGINE_TIMEOUT_S["container"]}


async def test_hung_native_engine_falls_back_and_is_counted() -> None:
    eng = Engines(nat=slow, con=ok())
    c, key = await make_client(eng)
    async with c:
        r = await post(c, key)
        assert r.status_code == 200
        assert r.json()["model"].startswith("container:")
        m = (await c.get("/metrics")).text
    assert 'fl_voice_engine_failover_total{engine="native",reason="timeout"} 1.0' in m
    assert 'fl_voice_stt_seconds_count{engine="container"} 1.0' in m


async def test_unreachable_and_loading_reasons_are_counted() -> None:
    eng = Engines(nat=boom, con=lambda _r: httpx.Response(503, json={"error": "model_unavailable"}))
    c, key = await make_client(eng)
    async with c:
        r = await post(c, key)
        assert r.status_code == 503
        assert r.headers["retry-after"] == "2"  # the page retries soon: a loading engine is parked for 2 s
        m = (await c.get("/metrics")).text
    assert 'fl_voice_engine_failover_total{engine="native",reason="unreachable"} 1.0' in m
    assert 'fl_voice_engine_failover_total{engine="container",reason="loading"} 1.0' in m


async def test_a_200_that_is_not_an_stt_reply_falls_through_to_the_next_engine() -> None:
    eng = Engines(nat=lambda _r: httpx.Response(200, json={"hello": "wrong service"}), con=ok())
    c, key = await make_client(eng)
    async with c:
        r = await post(c, key)
        assert r.status_code == 200
        assert r.json()["model"].startswith("container:")
        m = (await c.get("/metrics")).text
    assert 'fl_voice_engine_failover_total{engine="native",reason="error"} 1.0' in m


async def test_gated_silence_is_an_empty_answer_and_is_counted() -> None:
    gated = {**stt_reply(""), "lang": None, "ms": 0}
    c, key = await make_client(Engines(nat=lambda _r: httpx.Response(200, json=gated), con=ok()))
    async with c:
        r = await post(c, key)
        assert r.status_code == 200
        body = r.json()
        assert (body["wake"], body["intent"], body["transcript"], body["lang"]) == (False, "none", "", "other")
        m = (await c.get("/metrics")).text
    assert "fl_voice_empty_total 1.0" in m
    assert 'fl_voice_utterances_total{engine="native",intent="none",lang="other",wake="false"} 1.0' in m
