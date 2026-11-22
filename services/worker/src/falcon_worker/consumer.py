"""``fl:jobs`` consumer: idempotent, single-flight, publishes partials + final (docs/CONTRACTS.md).

Per verdict document (partial or final), in this order:
1. final only: upsert Postgres ``verdicts`` (+ ``evidence`` rows);
2. ``SET fl:verdict:last:<id> <json> EX 3600``;
3. ``PUBLISH fl:verdict:<id> <json>``;
4. final only: ``SET vc:<fingerprint> <verdict_id>`` (not for degraded verdicts) and
   ``XADD fl:events MAXLEN ~ 100000 * event <PlatformEvent JSON>`` (``verdict.created``).
The stream entry is acked after the final is published.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from collections.abc import Mapping
from typing import Any

from falcon_core.cascade import (
    Cascade,
    CascadeMetrics,
    CheckJob,
    reissue,
    url_sha256,
)
from falcon_core.cascade.assemble import build_verdict
from falcon_core.scoring.arbiter import ArbiterContext, score
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.url.canonical import canonicalize
from falcon_worker import keys
from falcon_worker.events import verdict_created
from falcon_worker.store import VerdictStore

log = logging.getLogger("falcon.worker")


def _dumps(doc: Mapping[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def _parse_doc(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


class RedisVerdictCache:
    """``vc:<fingerprint>`` -> verdict_id; the doc is read from ``fl:verdict:last:`` or Postgres."""

    def __init__(self, redis: Any, store: VerdictStore | None) -> None:
        self.r = redis
        self.store = store

    async def get(self, key: str) -> dict[str, Any] | None:
        vid = await self.r.get(keys.verdict_cache(key))
        if not vid:
            return None
        doc = _parse_doc(await self.r.get(keys.last_key(str(vid))))
        if doc is None and self.store is not None:
            try:
                doc = await self.store.get(str(vid))
            except Exception:  # noqa: BLE001 - store down: treat as a miss
                doc = None
        return doc if doc and doc.get("final") else None

    async def put(self, key: str, doc: dict[str, Any]) -> None:
        ttl = keys.VC_TTL_S.get(doc["verdict"])
        if ttl and not doc.get("degraded"):
            await self.r.set(keys.verdict_cache(key), doc["verdict_id"], ex=ttl)


class RedisSink:
    """``VerdictSink`` for one job: store, SET last, PUBLISH, then event (final only)."""

    def __init__(self, worker: Worker) -> None:
        self.w = worker
        self.final_doc: dict[str, Any] | None = None

    async def emit(self, doc: dict[str, Any], meta: Mapping[str, Any]) -> None:
        body = _dumps(doc)
        vid = doc["verdict_id"]
        if doc["final"]:
            try:
                await self.w.store.upsert(doc)
            except Exception as exc:  # noqa: BLE001 - Redis still carries the verdict for 1 h
                log.error("verdict store failed: %s", type(exc).__name__, extra={"verdict_id": vid})
        await self.w.r.set(keys.last_key(vid), body, ex=keys.LAST_TTL_S)
        await self.w.r.publish(keys.channel(vid), body)
        if doc["final"]:
            self.final_doc = doc
            try:
                event = verdict_created(doc, meta)
                await self.w.r.xadd(
                    keys.EVENTS_STREAM,
                    {"event": _dumps(event)},
                    maxlen=keys.EVENTS_MAXLEN,
                    approximate=True,
                )
            except Exception:  # noqa: BLE001 - an event failure must not lose the verdict
                log.exception("verdict.created emit failed", extra={"verdict_id": vid})


class Worker:
    def __init__(
        self,
        redis: Any,
        cascade: Cascade,
        store: VerdictStore,
        registry: BrandRegistry,
        metrics: CascadeMetrics,
        *,
        consumer: str | None = None,
        follower_wait_s: float = 30.0,
        poll_s: float = 0.1,
    ) -> None:
        self.r = redis
        self.cascade = cascade
        self.store = store
        self.registry = registry
        self.metrics = metrics
        self.consumer = consumer or f"worker-{os.environ.get('HOSTNAME') or socket.gethostname()}"
        self.follower_wait_s = follower_wait_s
        self.poll_s = poll_s

    # --- stream loop -----------------------------------------------------------------------

    async def ensure_group(self) -> None:
        from redis.exceptions import ResponseError

        try:
            await self.r.xgroup_create(keys.JOBS_STREAM, keys.JOBS_GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    @staticmethod
    def _entries(resp: Any) -> list[tuple[str, dict[str, str]]]:
        """Normalise XREADGROUP replies (RESP2 list or RESP3 dict shape)."""
        out: list[tuple[str, dict[str, str]]] = []
        if not resp:
            return out
        streams = resp.items() if isinstance(resp, dict) else resp
        for item in streams:
            _name, entries = item
            for entry in entries or []:
                entry_id, fields = entry
                if fields is None:  # deleted entry still pending
                    out.append((str(entry_id), {}))
                    continue
                if isinstance(fields, list):
                    fields = dict(zip(fields[::2], fields[1::2], strict=False))
                out.append((str(entry_id), {str(k): str(v) for k, v in fields.items()}))
        return out

    async def read_batch(self, pending: bool, count: int = 8, block_ms: int = 2000) -> int:
        stream_id = "0" if pending else ">"
        resp = await self.r.xreadgroup(
            keys.JOBS_GROUP,
            self.consumer,
            {keys.JOBS_STREAM: stream_id},
            count=count,
            block=None if pending else block_ms,
        )
        entries = self._entries(resp)
        if entries:
            await asyncio.gather(*(self.handle(eid, f) for eid, f in entries))
        return len(entries)

    async def run_forever(self) -> None:
        while True:
            try:
                await self.ensure_group()
                while await self.read_batch(pending=True):  # own pending entries after a restart
                    pass
                while True:
                    await self.read_batch(pending=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - keep consuming after Redis hiccups
                log.warning("job loop error, retrying: %s", type(exc).__name__)
                await asyncio.sleep(2)

    # --- one job ---------------------------------------------------------------------------

    async def _ack(self, entry_id: str) -> None:
        await self.r.xack(keys.JOBS_STREAM, keys.JOBS_GROUP, entry_id)

    async def handle(self, entry_id: str, fields: Mapping[str, str]) -> dict[str, Any] | None:
        """Process one stream entry. Returns the final doc it published (None if skipped)."""
        try:
            job = CheckJob.from_fields(fields)
        except ValueError as exc:
            log.error("malformed job %s: %s", entry_id, str(exc)[:200])
            await self.r.xadd(keys.JOBS_DEAD, {"entry_id": entry_id, "error": str(exc)[:200]})
            await self._ack(entry_id)
            return None

        vid = job.verdict_id
        claimed = await self.r.set(keys.claim_key(vid), entry_id, nx=True, ex=keys.CLAIM_TTL_S)
        if not claimed and str(await self.r.get(keys.claim_key(vid))) != entry_id:
            log.info("duplicate job skipped", extra={"verdict_id": vid})
            await self._ack(entry_id)
            return None
        last = _parse_doc(await self.r.get(keys.last_key(vid)))
        if last is not None and last.get("final"):
            await self._ack(entry_id)  # already finished (redelivery after publish)
            return None

        sink = RedisSink(self)
        try:
            if job.input_type != "url":
                await self._unsupported(job, sink)
            else:
                await self._url(job, sink)
        finally:
            await self._ack(entry_id)
        return sink.final_doc

    async def _unsupported(self, job: CheckJob, sink: RedisSink) -> None:
        """message/email/image pipelines are not built yet: answer degraded, never silent."""
        await self.r.delete(keys.blob_key(job.verdict_id))
        t0 = time.perf_counter()
        result = score(
            [],
            None,
            ArbiterContext(
                input_type=job.input_type,
                extra_degraded_reasons=(f"input_type_not_supported_yet:{job.input_type}",),
            ),
        )
        doc = build_verdict(
            result,
            verdict_id=job.verdict_id,
            input_type=job.input_type,
            tier="T0",
            final=True,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            registry=self.registry,
            input_fingerprint=job.fingerprint,
            source=job.source,
        )
        self.metrics.checks.labels(job.input_type, doc["verdict"], "T0", "none", job.source).inc()
        self.metrics.degraded.inc()
        await sink.emit(doc, {})

    async def _url(self, job: CheckJob, sink: RedisSink) -> None:
        url = job.url
        if url is None:
            await self.cascade.run_url(job.verdict_id, "", sink, source=job.source)
            return
        c = canonicalize(url)
        key = job.fingerprint or (url_sha256(c) if c.ok else None)
        if key is None:
            await self.cascade.run_url(job.verdict_id, url, sink, source=job.source)
            return
        lock = keys.worker_single_flight(key)
        if await self.r.set(lock, job.verdict_id, nx=True, ex=keys.SINGLE_FLIGHT_TTL_S):
            try:
                await self.cascade.run_url(
                    job.verdict_id, url, sink, source=job.source, cache_key=key
                )
            finally:
                if str(await self.r.get(lock)) == job.verdict_id:
                    await self.r.delete(lock)
            return
        leader = await self.r.get(lock)
        doc = await self._wait_for_leader(str(leader) if leader else None)
        if doc is None:  # leader vanished or too slow: run it ourselves
            await self.cascade.run_url(job.verdict_id, url, sink, source=job.source, cache_key=key)
            return
        self.metrics.cache_hits.labels("single_flight").inc()
        out = reissue(
            doc,
            verdict_id=job.verdict_id,
            source=job.source,
            latency_ms=int((time.time() - job.submitted_at.timestamp()) * 1000),
            note=f"Shared result of an identical check in flight ({str(leader)[:32]})",
            input_fingerprint=doc.get("input_fingerprint"),
        )
        self.metrics.checks.labels(
            "url", out["verdict"], out["tier_reached"], out["model_route"], job.source
        ).inc()
        reg = c.registrable or c.host
        await sink.emit(out, {"registrable_domain": reg})

    async def _wait_for_leader(self, leader: str | None) -> dict[str, Any] | None:
        if not leader:
            return None
        deadline = time.monotonic() + self.follower_wait_s
        while time.monotonic() < deadline:
            doc = _parse_doc(await self.r.get(keys.last_key(leader)))
            if doc is not None and doc.get("final"):
                return doc
            await asyncio.sleep(self.poll_s)
        return None
