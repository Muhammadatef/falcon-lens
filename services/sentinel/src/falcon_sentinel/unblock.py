"""`make unblock ID=<action_id>`: revert a block (Redis key + table), audit it, count fl_blocks_reverted_total.

When to use it:
    When a Sentinel block was approved by mistake or is no longer wanted.

How to run:
    make unblock ID=act_xxx
    DATABASE_URL=... REDIS_URL=... uv run python -m falcon_sentinel.unblock act_xxx

Inputs:
    The action id (must start with act_) and env DATABASE_URL and REDIS_URL, which must be reachable from
    your machine (the compose defaults are internal to Docker). The operator name is taken from $USER.

Outputs / side effects:
    Deletes the block key in Redis, updates the action row in Postgres, writes an audit entry, and prints
    the result. The counter fl_blocks_reverted_total is incremented only inside this short-lived process.
    Exit code 0 on success, 1 if the revert is refused, 2 on wrong usage or missing env vars.
"""

from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as aioredis

from falcon_core.tools.sentinel import ToolContext, ToolError, unblock

from .db import IncidentCache, PgRepo
from .metrics import BLOCKS_REVERTED, SentinelMetrics


async def amain(action_id: str, operator: str) -> int:
    """Revert one action: remove the block, update the database, audit it."""
    dsn, url = os.environ.get("DATABASE_URL"), os.environ.get("REDIS_URL")
    if not dsn or not url:
        print("DATABASE_URL and REDIS_URL must be set", file=sys.stderr)
        return 2
    repo = PgRepo(dsn)
    await repo.init()
    client = aioredis.from_url(url, decode_responses=True)
    try:
        cache = IncidentCache(repo)
        await cache.load()
        try:
            res = await unblock(
                ToolContext(incidents=cache, repo=repo, redis=client, metrics=SentinelMetrics()),
                action_id,
                operator,
            )
        except ToolError as exc:
            print(f"unblock failed: {exc}", file=sys.stderr)
            return 1
        print(res, f"(fl_blocks_reverted_total={BLOCKS_REVERTED._value.get():.0f} in this process)")  # noqa: SLF001
        return 0
    finally:
        await client.aclose()
        await repo.close()


def main() -> int:
    """Check the arguments (act_<id>) and run `amain`; 2 on bad usage."""
    if len(sys.argv) != 2 or not sys.argv[1].startswith("act_"):
        print("usage: python -m falcon_sentinel.unblock act_<id>", file=sys.stderr)
        return 2
    return asyncio.run(amain(sys.argv[1], os.environ.get("USER", "operator")))


if __name__ == "__main__":
    raise SystemExit(main())
