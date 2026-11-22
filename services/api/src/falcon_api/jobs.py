"""Job submission, single-flight, verdict lookup and the watch loop (see docs/CONTRACTS.md)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from ulid import ULID

from falcon_api.problem import Problem
from falcon_api.store import StoreUnavailableError, VerdictStore

log = logging.getLogger("falcon.api.jobs")

STREAM = "fl:jobs"
STREAM_MAXLEN = 5000
JOB_TTL_S = 3600
SINGLE_FLIGHT_TTL_S = 120
BLOB_TTL_S = 600
VC_TTL_S = {"dangerous": 24 * 3600, "suspicious": 3600, "no_warning_signs": 6 * 3600}


def new_verdict_id() -> str:
    return f"vd_{ULID()}"


def last_key(verdict_id: str) -> str:
    return f"fl:verdict:last:{verdict_id}"


def channel(verdict_id: str) -> str:
    return f"fl:verdict:{verdict_id}"


def public_doc(doc: dict[str, Any], authenticated: bool) -> dict[str, Any]:
    """Anonymous callers never get a screenshot URL."""
    out = dict(doc)
    if not authenticated:
        out["screenshot_url"] = None
    return out


def _parse(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


class Jobs:
    def __init__(self, redis: Redis, store: VerdictStore | None) -> None:
        self.r = redis
        self.store = store

    async def latest(self, verdict_id: str, use_pg: bool = True) -> dict[str, Any] | None:
        """Best known verdict: final from Postgres, else the latest partial in Redis."""
        partial = _parse(await self.r.get(last_key(verdict_id)))
        if partial is not None and partial.get("final"):
            return partial
        if use_pg and self.store is not None:
            try:
                final = await self.store.get(verdict_id)
            except StoreUnavailableError:
                final = None
            if final is not None:
                return final
        return partial

    async def known(self, verdict_id: str) -> bool:
        if await self.r.exists(f"fl:job:{verdict_id}"):
            return True
        return await self.latest(verdict_id) is not None

    async def enqueue(
        self,
        *,
        input_type: str,
        payload: dict[str, Any],
        fingerprint: str,
        source: str,
        blob_b64: str | None = None,
    ) -> tuple[str, str]:
        """Return (verdict_id, state) with state in {"queued", "attached", "cached"}."""
        try:
            cached = await self.r.get(f"vc:{fingerprint}")
            if cached:
                cached_id = cached.decode() if isinstance(cached, bytes) else str(cached)
                doc = await self.latest(cached_id)
                if doc is not None and doc.get("final"):
                    return cached_id, "cached"
            verdict_id = new_verdict_id()
            if not await self.r.set(f"sf:{fingerprint}", verdict_id, nx=True, ex=SINGLE_FLIGHT_TTL_S):
                existing = await self.r.get(f"sf:{fingerprint}")
                if existing:
                    return str(existing), "attached"
                await self.r.set(f"sf:{fingerprint}", verdict_id, ex=SINGLE_FLIGHT_TTL_S)
            await self.r.set(f"fl:job:{verdict_id}", fingerprint, ex=JOB_TTL_S)
            if blob_b64 is not None:
                await self.r.set(f"fl:blob:{verdict_id}", blob_b64, ex=BLOB_TTL_S)
            await self.r.xadd(
                STREAM,
                {
                    "verdict_id": verdict_id,
                    "input_type": input_type,
                    "payload_json": json.dumps(payload, separators=(",", ":")),
                    "submitted_at": datetime.now(UTC).isoformat(),
                    "source": source,
                },
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        except RedisError as exc:
            log.error("redis unavailable on enqueue: %s", type(exc).__name__)
            raise Problem(503, "queue-unavailable", "Queue unavailable") from exc
        return verdict_id, "queued"

    async def note_final(self, doc: dict[str, Any]) -> None:
        """Populate the verdict cache `vc:<sha>` (best effort) when a final verdict is observed."""
        if not (doc.get("final") and doc.get("verdict") in VC_TTL_S and doc.get("verdict_id")):
            return
        try:
            fp = await self.r.get(f"fl:job:{doc['verdict_id']}")
            fingerprint = fp.decode() if isinstance(fp, bytes) else fp
            if fingerprint:
                await self.r.set(f"vc:{fingerprint}", doc["verdict_id"], ex=VC_TTL_S[doc["verdict"]])
        except RedisError:
            pass

    async def watch(self, verdict_id: str, poll_s: float = 1.0) -> AsyncIterator[dict[str, Any] | None]:
        """Yield each distinct verdict doc until final; yield None on idle ticks (~0.25 s).

        Combines Redis pub/sub (low latency) with a periodic poll of the last-known/final
        stores (no lost updates if a message is missed or the subscriber attached late).
        """
        pubsub = self.r.pubsub()
        await pubsub.subscribe(channel(verdict_id))
        last_sig: str | None = None
        next_poll = 0.0
        try:
            while True:
                doc: dict[str, Any] | None = None
                try:
                    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.25)
                except RedisError:
                    msg = None
                    await asyncio.sleep(0.25)
                if msg:
                    doc = _parse(msg.get("data"))
                if doc is None and time.monotonic() >= next_poll:
                    next_poll = time.monotonic() + poll_s
                    try:
                        doc = await self.latest(verdict_id)
                    except RedisError:
                        doc = None
                if doc is None:
                    yield None
                    continue
                sig = json.dumps(doc, sort_keys=True)
                if sig == last_sig:
                    yield None
                    continue
                last_sig = sig
                yield doc
                if doc.get("final"):
                    return
        finally:
            try:
                await pubsub.unsubscribe(channel(verdict_id))
                await pubsub.aclose()  # type: ignore[no-untyped-call]
            except (RedisError, RuntimeError):
                pass
