"""Wiring for the hunt task (main.py lifespan) and the one-shot `make hunt-once` command."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from sentinel_core.hunt.config import default_config

from falcon_core.signals.brands.registry import default_registry
from falcon_core.telemetry import metrics as tm

from .clock import Clock, SystemClock
from .http import HuntHTTP, api_client
from .scheduler import HuntScheduler, allow_hosts, make_guard
from .settings import HuntSettings
from .store import HuntStore
from .submit import Submitter

log = logging.getLogger("falcon.sentinel.hunt")
JOBS_STREAM = "fl:jobs"


def jobs_lag_of(redis: Any) -> Any:
    async def lag() -> int:
        """Largest consumer-group lag (or pending count) on fl:jobs; 0 when unknown."""
        try:
            groups = await redis.xinfo_groups(JOBS_STREAM)
        except Exception:  # noqa: BLE001 - no stream yet = no backlog
            return 0
        worst = 0
        for g in groups or []:
            v = g.get("lag")
            if v is None:
                v = g.get("pending", 0)
            worst = max(worst, int(v or 0))
        return worst

    return lag


async def build_scheduler(
    stack: AsyncExitStack,
    settings: HuntSettings,
    store: HuntStore,
    redis: Any,
    *,
    clock: Clock | None = None,
    brands: list[str] | None = None,
    egress_transport: Any = None,
    api_transport: Any = None,
) -> HuntScheduler:
    clock = clock or SystemClock()
    active = settings.active_sources()
    http: HuntHTTP | None = None
    if any(s in active for s in ("permutation", "ct_lookup", "ct_search")):
        http = HuntHTTP(
            proxy=settings.proxy, allow_hosts=allow_hosts(settings), guard=make_guard(redis), transport=egress_transport
        )
        stack.push_async_callback(http.aclose)
    submitter: Submitter | None = None
    if settings.api_key:
        client = await stack.enter_async_context(api_client(settings.api_url, settings.api_key, api_transport))
        submitter = Submitter(client)
    else:
        log.warning("FL_HUNT_API_KEY unset: candidates are recorded but never submitted")
    await store.init()
    return HuntScheduler(
        settings=settings,
        config=default_config(),
        registry=default_registry(),
        store=store,
        redis=redis,
        clock=clock,
        http=http,
        submitter=submitter,
        jobs_lag=jobs_lag_of(redis),
        brands=brands,
    )


async def hunt_loop(sched: HuntScheduler, settings: HuntSettings, clock: Clock | None = None) -> None:
    clock = clock or SystemClock()
    while True:
        try:
            await sched.run_cycle()
        except Exception:  # noqa: BLE001
            log.exception("hunt loop iteration failed")
        await clock.sleep(settings.interval_min * 60)


def mark_enabled(settings: HuntSettings) -> None:
    label = (
        "live" if any(s in settings.active_sources() for s in ("permutation", "ct_lookup", "ct_search")) else "fixture"
    )
    tm.HUNT_ENABLED.labels(label).set(1 if settings.enabled else 0)


def start(settings: HuntSettings, sched: HuntScheduler) -> asyncio.Task[None]:
    return asyncio.create_task(hunt_loop(sched, settings))


async def maybe_start(
    stack: AsyncExitStack, settings: HuntSettings, store: HuntStore, redis: Any, **kw: Any
) -> asyncio.Task[None] | None:
    """Kill switch: with FL_HUNT_ENABLED false nothing is built (no HTTP client) and no task exists."""
    mark_enabled(settings)
    if not settings.enabled:
        return None
    sched = await build_scheduler(stack, settings, store, redis, **kw)
    log.info("hunt mode on", extra={"hunt_sources": list(settings.active_sources())})
    return start(settings, sched)
