"""Falcon Lens worker: health server + ``fl:jobs`` consumer running the cascade (T-012).

Network note: the worker is the only service besides egress-proxy that shares a network with the
sandbox (`sandbox_ctl`). Docker networks are not directional, so the sandbox can reach this port.
The worker therefore exposes ONLY /healthz, /readyz and /metrics (plus /metrics/sandbox) on it:
never a job or control API. Jobs arrive through Redis only.

When to use it:
    You do not run it by hand; the `worker` container starts it. `make smoke` proves it works.

How to run:
    make up                                   (direct: uv run python -m falcon_worker.main)

Inputs:
    Settings from env (Redis URL, optional database URL, FL_SANDBOX_TOKEN or FL_SANDBOX_API_KEY),
    FL_SANDBOX_URL (default http://sandbox:8000), FL_SSRF_ALLOW_HOSTS (only honoured in local, demo and ci
    environments), FL_EGRESS_PROXY (route reputation lookups through the egress proxy), FL_OPENPHISH_FEED_DIR
    and FL_OPENPHISH_REFRESH_S (default 900 seconds).

Outputs / side effects:
    Reads jobs from the Redis stream fl:jobs and stores verdicts (Redis cache, and Postgres when DATABASE_URL
    is set; it runs the table migration at start). Calls the sandbox over the internal network and the
    reputation services through the SSRF-guarded client. If the OpenPhish feed folder is mounted it reads it
    (local files only) and refreshes the Redis feed mirror, publishing feed.updated events on fl:events.
    Exposes /healthz, /readyz and /metrics on port 8000.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Response
from fastapi.responses import PlainTextResponse

from falcon_core.cascade import Cascade, CascadeDeps, CascadeMetrics, HttpSandboxClient
from falcon_core.cascade.favicons import load_brand_favicons
from falcon_core.config import get_settings
from falcon_core.security import GuardedHTTPClient, GuardPolicy, set_default_on_block
from falcon_core.service import create_app, run
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.cache import RedisCache
from falcon_core.signals.reputation.external import FEED_POST_HOSTS
from falcon_core.signals.reputation.mirror import FeedMirror, redis_publisher, run_refresh_loop
from falcon_worker.ai import build_ai
from falcon_worker.consumer import RedisVerdictCache, Worker
from falcon_worker.store import MemoryStore, PgStore, VerdictStore

log = logging.getLogger("falcon.worker")
settings = get_settings()

REDIS_URL = settings.redis_url or "redis://redis:6379/0"
SANDBOX_URL = os.environ.get("FL_SANDBOX_URL", "http://sandbox:8000")
SANDBOX_METRICS_URL = f"{SANDBOX_URL}/metrics"
REFRESH_S = float(os.environ.get("FL_OPENPHISH_REFRESH_S", "900"))


ALLOWLIST_ENVS = frozenset({"local", "demo", "ci"})


def guard_policy() -> GuardPolicy:
    """``FL_SSRF_ALLOW_HOSTS`` (comma list) widens the guard for internal fixture hosts only.

    Fail closed, same rule as the sandbox: honoured only when ``FL_ENV`` is local, demo or ci.
    """
    raw = os.environ.get("FL_SSRF_ALLOW_HOSTS", "")
    hosts = frozenset(h.strip().lower() for h in raw.split(",") if h.strip())
    if hosts and os.environ.get("FL_ENV") not in ALLOWLIST_ENVS:
        log.error("FL_SSRF_ALLOW_HOSTS ignored outside local/demo/ci")
        hosts = frozenset()
    return GuardPolicy(allow_hosts=hosts)


def sandbox_token() -> str | None:
    for secret in (settings.fl_sandbox_token, settings.fl_sandbox_api_key):
        if secret is not None:
            return secret.get_secret_value()
    return None


def signal_http(metrics: CascadeMetrics) -> GuardedHTTPClient:
    """The shared ``ctx.http`` for network signals (RDAP, crt.sh, GSB, URLhaus).

    Production SSRF policy, plus POST only to the two reputation API hosts. ``FL_EGRESS_PROXY``
    (e.g. http://egress-proxy:3128) routes it through the filtering egress proxy; unset = direct,
    with the guard's own DNS pinning.
    """
    proxy = os.environ.get("FL_EGRESS_PROXY") or None
    return GuardedHTTPClient(
        policy=GuardPolicy(post_allow_hosts=FEED_POST_HOSTS), proxy=proxy, on_block=metrics.on_ssrf_block
    )


def feed_dir() -> Path:
    return Path(os.environ.get("FL_OPENPHISH_FEED_DIR", "/app/data/private/feeds/openphish"))


def build_worker(
    app: FastAPI, redis: Any, metrics: CascadeMetrics | None = None
) -> tuple[Worker, VerdictStore, list[Any]]:
    """Wire the cascade. Returns the worker, its store and the clients to close on shutdown."""
    metrics = metrics or CascadeMetrics()
    set_default_on_block(metrics.on_ssrf_block)
    dsn = settings.database_url.get_secret_value() if settings.database_url else None
    store: VerdictStore = PgStore(dsn) if dsn else MemoryStore()
    sandbox = HttpSandboxClient(SANDBOX_URL, token=sandbox_token())
    http = signal_http(metrics)
    kv = RedisCache(redis)
    registry = default_registry()
    deps = CascadeDeps(
        registry=registry,
        sandbox=sandbox,
        metrics=metrics,
        cache=RedisVerdictCache(redis, store),
        guard_policy=guard_policy(),
        favicons=load_brand_favicons(),
        signal_http=http,
        signal_cache=kv,
        mirror=FeedMirror(kv),
        **build_ai(http=http, cache=kv, mirror=FeedMirror(kv), registry=registry, sandbox=sandbox),
    )
    return Worker(redis, Cascade(deps), store, registry, metrics), store, [sandbox, http]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import redis.asyncio as aioredis

    client = aioredis.from_url(REDIS_URL, decode_responses=True)
    worker, store, closers = build_worker(app, client)
    try:
        await store.migrate()
    except Exception as exc:  # noqa: BLE001 - start anyway; upserts retry per verdict
        log.error("migration failed (will retry on next start): %s", type(exc).__name__)
    tasks = [asyncio.create_task(worker.run_forever())]
    fdir = feed_dir()
    if fdir.is_dir():
        # Local files only (the collector writes them); no network. Emits feed.updated on fl:events.
        tasks.append(
            asyncio.create_task(
                run_refresh_loop(RedisCache(client), fdir, interval_s=REFRESH_S, publish=redis_publisher(client))
            )
        )
    else:
        log.warning("openphish feed dir %s not mounted: mirror is only what is already in Redis", fdir)
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError):
                await t
        for c in closers:
            await c.aclose()
        await store.close()
        await client.aclose()


deps: dict[str, str] = {"redis": REDIS_URL}
if settings.database_url:
    deps["postgres"] = settings.database_url.get_secret_value()

app = create_app("worker", deps=deps, lifespan=lifespan, title="Falcon Lens worker")


@app.get("/metrics/sandbox", include_in_schema=False)
async def sandbox_metrics() -> Response:
    """Relay the sandbox's metrics so Prometheus never needs a route into the sandbox network."""
    token = settings.fl_sandbox_token
    headers = {"Authorization": f"Bearer {token.get_secret_value()}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(SANDBOX_METRICS_URL, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("sandbox metrics relay failed: %s", exc)
        return PlainTextResponse("# sandbox metrics unavailable\n", status_code=503)
    return PlainTextResponse(resp.text, media_type=resp.headers.get("content-type", "text/plain"))


if __name__ == "__main__":
    run(app)
