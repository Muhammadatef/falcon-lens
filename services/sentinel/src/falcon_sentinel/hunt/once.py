"""One hunt cycle for one brand, run by an operator: `make hunt-once BRAND=<brand_id>`.

What it does:
    Runs exactly one hunt cycle (HUNTER.md section 3) limited to one brand from data/brands.yaml, with the same
    sources, pause key, quotas, prescore threshold and egress proxy as the background task, then prints counts
    by status and the defanged confirmed / submitted names. It is the operator's explicit act, so it runs even
    when FL_HUNT_ENABLED is false (the master switch only governs the background task); `fl:hunt:paused` still
    stops it.

How to run:
    make hunt-once BRAND=falcon_demo_bank         (inside the sentinel container)
    uv run python -m falcon_sentinel.hunt.once --brand <id>

Inputs:
    DATABASE_URL, REDIS_URL, FL_HUNT_* (see .env.example). Needs FL_HUNT_API_KEY to submit anything.

Outputs / side effects:
    Rows in hunt_candidates / hunt_cycles; DoH and (if listed in FL_HUNT_SOURCES) crt.sh requests through
    hunt-egress; at most FL_HUNT_SUBMIT_MAX_PER_HOUR checks submitted to the API. Never prints a live domain.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack

from sentinel_core.hunt.candidates import defang

from falcon_core.signals.brands.registry import default_registry

from .runtime import build_scheduler
from .settings import HuntSettings
from .store import MemoryHuntStore, PgHuntStore


async def main(brand: str) -> int:
    if brand not in {b.brand_id for b in default_registry().brands}:
        print(f"unknown brand_id {brand!r} (see data/brands.yaml)", file=sys.stderr)
        return 2
    settings = HuntSettings.from_env()
    dsn, redis_url = os.environ.get("DATABASE_URL"), os.environ.get("REDIS_URL")
    async with AsyncExitStack() as stack:
        redis = None
        if redis_url:
            import redis.asyncio as aioredis

            redis = aioredis.from_url(redis_url, decode_responses=True)
            stack.push_async_callback(redis.aclose)
        if dsn:
            from psycopg_pool import AsyncConnectionPool

            pool = AsyncConnectionPool(dsn, min_size=1, max_size=3, open=False, kwargs={"autocommit": True})
            await pool.open()
            stack.push_async_callback(pool.close)
            store: PgHuntStore | MemoryHuntStore = PgHuntStore(
                pool, os.environ.get("FL_DATABASE_OWNER_URL") or None, os.environ.get("FL_SENTINEL_DB_ROLE") or None
            )
        else:
            print("DATABASE_URL unset: results are kept in memory only", file=sys.stderr)
            store = MemoryHuntStore()
        sched = await build_scheduler(stack, settings, store, redis, brands=[brand])
        res = await sched.run_cycle()
        rows = [c for c in await store.list(None, limit=5000) if c.brand_id == brand]
        counts: dict[str, int] = {}
        for c in rows:
            counts[c.status] = counts.get(c.status, 0) + 1
        out = {
            "brand_id": brand,
            "outcome": res["outcome"],
            "stats": res["stats"],
            "sources": list(settings.active_sources()),
            "counts": counts,
            "submitted_or_confirmed": [
                {"domain": defang(c.domain), "status": c.status, "prescore": c.prescore, "reasons": list(c.reasons)}
                for c in rows
                if c.status in ("submitted", "confirmed", "cleared", "already_known")
            ][:50],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if res["outcome"] in ("ok", "paused") else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run one hunt cycle for one brand.")
    ap.add_argument("--brand", required=True)
    raise SystemExit(asyncio.run(main(ap.parse_args().brand)))
