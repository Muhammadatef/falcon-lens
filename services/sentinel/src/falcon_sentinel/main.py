"""Falcon Lens Sentinel: health server + stream consumer + LangGraph triage + incident/approval API."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import socket
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
import redis.asyncio as aioredis
import yaml
from fastapi import FastAPI, Header, HTTPException
from redis.exceptions import RedisError
from sentinel_core.incidents import Sentinel

from falcon_core.config import get_settings
from falcon_core.service import create_app, run
from falcon_core.tools.sentinel import ToolContext

from .consumer import Consumer
from .db import IncidentCache, PgRepo
from .graph import ApprovalError, Deps, TriageRunner, set_default_runner
from .llm import LLMClient, OpenAICompatLLM, StubLLM
from .metrics import SentinelMetrics

log = logging.getLogger("falcon.sentinel")
settings = get_settings()
CONSUMER = f"sentinel-{os.environ.get('HOSTNAME') or socket.gethostname()}"
BRANDS = Path(__file__).resolve().parents[4] / "data" / "brands.yaml"


def official_domains() -> list[str]:
    if not BRANDS.exists():
        return []
    data = yaml.safe_load(BRANDS.read_text())
    return [d for b in data.get("brands", []) for d in b.get("verified_domains", [])]


def make_llm() -> LLMClient:
    if os.environ.get("FL_SENTINEL_LLM", "ollama") == "stub":
        return StubLLM()
    return OpenAICompatLLM(
        settings.ollama_base_url, os.environ.get("FL_SENTINEL_MODEL", "inkling-2-mini-chat")
    )


class Runtime:
    runner: TriageRunner | None = None
    cache: IncidentCache | None = None
    repo: PgRepo | None = None


rt = Runtime()


async def triage_loop(consumer: Consumer, runner: TriageRunner, queue: asyncio.Queue[str]) -> None:
    while True:
        iid = await queue.get()
        try:
            await runner.run(iid)
        except Exception:  # noqa: BLE001 - checkpoint keeps the run; resume_unfinished retries after restart
            log.exception("triage failed", extra={"incident_id": iid})


async def consume_loop(consumer: Consumer) -> None:
    while True:
        try:
            await consumer.run_once(block_ms=2000)
        except (RedisError, OSError) as exc:
            log.warning("redis unavailable, retrying: %s", exc)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    dsn = settings.database_url.get_secret_value() if settings.database_url else None
    if not dsn or not settings.redis_url:
        log.warning("DATABASE_URL/REDIS_URL not set: sentinel runs idle")
        yield
        return
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncExitStack() as stack:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        stack.push_async_callback(client.aclose)
        repo = PgRepo(dsn)
        await repo.init()
        stack.push_async_callback(repo.close)
        saver = await stack.enter_async_context(AsyncPostgresSaver.from_conn_string(dsn))
        await saver.setup()
        http = await stack.enter_async_context(httpx.AsyncClient(timeout=10))
        cache = IncidentCache(repo)
        ctx = ToolContext(
            incidents=cache,
            repo=repo,
            redis=client,
            http=http,
            alertmanager_url=os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093"),
            metrics=SentinelMetrics(),
        )
        runner = TriageRunner(Deps(llm=make_llm(), tools=ctx), saver)
        set_default_runner(runner)
        rt.runner, rt.cache, rt.repo = runner, cache, repo
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def on_incidents(ids: list[str]) -> None:
            for i in ids:
                inc = cache.get(i)
                if inc and inc["status"] == "open":
                    queue.put_nowait(i)

        consumer = Consumer(
            client,
            repo,
            cache,
            Sentinel(cache, official_domains=official_domains()),
            CONSUMER,
            on_incidents,
        )
        await consumer.setup()
        await runner.resume_unfinished()
        tasks = [
            asyncio.create_task(consume_loop(consumer)),
            asyncio.create_task(triage_loop(consumer, runner, queue)),
        ]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with suppress(asyncio.CancelledError):
                    await t


app = create_app(
    "sentinel",
    deps={"redis": settings.redis_url or "redis://redis:6379/0"},
    lifespan=lifespan,
    title="Falcon Lens Sentinel",
)


def _operator(key: str | None) -> str:
    want = settings.fl_operator_key.get_secret_value() if settings.fl_operator_key else None
    if not want or not key or not hmac.compare_digest(key.encode(), want.encode()):
        raise HTTPException(401, "operator key required")
    return "operator"


@app.get("/internal/incidents")
async def list_incidents(status: str | None = None) -> list[dict[str, Any]]:
    incs = rt.cache.all() if rt.cache else []
    return [i for i in incs if status in (None, i["status"])]


@app.get("/internal/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict[str, Any]:
    inc = rt.cache.get(incident_id) if rt.cache else None
    if inc is None:
        raise HTTPException(404, "not found")
    return inc


async def _decide(incident_id: str, action_id: str, who: str, ok: bool) -> dict[str, Any]:
    if rt.runner is None:
        raise HTTPException(503, "sentinel idle")
    try:
        await (rt.runner.approve if ok else rt.runner.reject)(incident_id, action_id, who)
    except ApprovalError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "incident_id": incident_id,
        "action_id": action_id,
        "decision": "approved" if ok else "rejected",
    }


@app.post("/internal/incidents/{incident_id}/actions/{action_id}/approve")
async def approve(
    incident_id: str, action_id: str, x_operator_key: str | None = Header(None)
) -> dict[str, Any]:
    return await _decide(incident_id, action_id, _operator(x_operator_key), True)


@app.post("/internal/incidents/{incident_id}/actions/{action_id}/reject")
async def reject(
    incident_id: str, action_id: str, x_operator_key: str | None = Header(None)
) -> dict[str, Any]:
    return await _decide(incident_id, action_id, _operator(x_operator_key), False)


if __name__ == "__main__":
    run(app)
