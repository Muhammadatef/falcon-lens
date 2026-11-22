"""Falcon Lens worker: health server + ``fl:jobs`` consumer running the cascade (T-012)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from falcon_core.cascade import Cascade, CascadeDeps, CascadeMetrics, HttpSandboxClient
from falcon_core.cascade.favicons import load_brand_favicons
from falcon_core.config import get_settings
from falcon_core.security import GuardPolicy, set_default_on_block
from falcon_core.service import create_app, run
from falcon_core.signals.brands.registry import default_registry
from falcon_worker.consumer import RedisVerdictCache, Worker
from falcon_worker.store import MemoryStore, PgStore, VerdictStore

log = logging.getLogger("falcon.worker")
settings = get_settings()

REDIS_URL = settings.redis_url or "redis://redis:6379/0"
SANDBOX_URL = os.environ.get("FL_SANDBOX_URL", "http://sandbox:8000")


def guard_policy() -> GuardPolicy:
    """``FL_SSRF_ALLOW_HOSTS`` (comma list) widens the guard for internal fixture hosts only.

    Refused when ``FL_ENV=production`` (the production policy is never widened).
    """
    raw = os.environ.get("FL_SSRF_ALLOW_HOSTS", "")
    hosts = frozenset(h.strip().lower() for h in raw.split(",") if h.strip())
    if hosts and settings.fl_env == "production":
        log.error("FL_SSRF_ALLOW_HOSTS ignored in production")
        hosts = frozenset()
    return GuardPolicy(allow_hosts=hosts)


def build_worker(app: FastAPI, redis: Any) -> tuple[Worker, VerdictStore, HttpSandboxClient]:
    metrics = CascadeMetrics(app.state.registry)
    set_default_on_block(metrics.on_ssrf_block)
    dsn = settings.database_url.get_secret_value() if settings.database_url else None
    store: VerdictStore = PgStore(dsn) if dsn else MemoryStore()
    key = settings.fl_sandbox_api_key.get_secret_value() if settings.fl_sandbox_api_key else None
    sandbox = HttpSandboxClient(SANDBOX_URL, api_key=key)
    registry = default_registry()
    deps = CascadeDeps(
        registry=registry,
        sandbox=sandbox,
        metrics=metrics,
        cache=RedisVerdictCache(redis, store),
        guard_policy=guard_policy(),
        favicons=load_brand_favicons(),
    )
    return Worker(redis, Cascade(deps), store, registry, metrics), store, sandbox


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import redis.asyncio as aioredis

    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    worker, store, sandbox = build_worker(app, client)
    try:
        await store.migrate()
    except Exception as exc:  # noqa: BLE001 - start anyway; upserts retry per verdict
        log.error("migration failed (will retry on next start): %s", type(exc).__name__)
    task = asyncio.create_task(worker.run_forever())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await sandbox.aclose()
        await store.close()
        await client.aclose()


deps: dict[str, str] = {"redis": REDIS_URL}
if settings.database_url:
    deps["postgres"] = settings.database_url.get_secret_value()

app = create_app("worker", deps=deps, lifespan=lifespan, title="Falcon Lens worker")

if __name__ == "__main__":
    run(app)
