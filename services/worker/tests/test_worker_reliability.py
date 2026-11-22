"""Worker reliability: no ack on failure, reclaim of idle entries, dead-letter after N deliveries,
exactly one final, no cache poisoning (review PR-18 items 2-5)."""

from __future__ import annotations

import json
from typing import Any

from test_worker_consumer import VERDICT, Rig

from falcon_core.cascade import StubSandboxClient
from falcon_core.cascade.engine import url_sha256
from falcon_core.cascade.testing import (
    DEMO_BENIGN_URL,
    DEMO_LOOKALIKE_URL,
    SlowSandbox,
    benign_features,
    phish_features,
)
from falcon_core.signals.url.canonical import canonicalize
from falcon_worker import keys


class PublishFailure:
    """Patch ``publish`` on a fakeredis client: fail the first ``n`` calls whose doc matches."""

    def __init__(self, rig: Rig, n: int = 10**9, final_only: bool = False) -> None:
        self.real = rig.r.publish
        self.left = n
        self.final_only = final_only
        self.seen: list[dict[str, Any]] = []
        rig.r.publish = self

    async def __call__(self, channel: str, body: str) -> int:
        doc = json.loads(body)
        if self.left > 0 and (doc["final"] or not self.final_only):
            self.left -= 1
            raise ConnectionError("redis publish down")
        self.seen.append(doc)
        result: int = await self.real(channel, body)
        return result


async def _pending(rig: Rig) -> int:
    return int((await rig.r.xpending(keys.JOBS_STREAM, keys.JOBS_GROUP))["pending"])


async def test_final_publish_failure_leaves_entry_pending_and_does_not_poison_cache() -> None:
    rig = Rig(StubSandboxClient(default=phish_features()), reclaim_idle_ms=0)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_LOOKALIKE_URL)
    pf = PublishFailure(rig, n=1, final_only=True)
    await rig.worker.read_batch(pending=False, block_ms=100)  # must not raise

    assert await _pending(rig) == 1  # not acked
    fp = url_sha256(canonicalize(DEMO_LOOKALIKE_URL))
    assert await rig.r.get(keys.verdict_cache(fp)) is None  # vc only after a successful publish
    assert await rig.r.xlen(keys.EVENTS_STREAM) == 0
    assert await rig.r.get(keys.done_key(vid)) is None

    # Retry via reclaim: the stored final is finished, not re-scored.
    assert await rig.worker.reclaim() == 1
    finals = [d for d in pf.seen if d["final"]]
    assert len(finals) == 1
    final = finals[0]
    VERDICT.validate(final)
    assert final["verdict"] == "dangerous" and final["degraded"] is False
    assert "internal_error" not in json.dumps(final)
    assert rig.store.verdicts[vid] == final
    assert await rig.r.get(keys.verdict_cache(fp)) == vid
    assert await rig.r.xlen(keys.EVENTS_STREAM) == 1
    assert await _pending(rig) == 0


async def test_partial_publish_failure_reruns_and_publishes_one_final() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    rig = Rig(sandbox, reclaim_idle_ms=0)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    pf = PublishFailure(rig, n=1)  # the T0 partial fails
    await rig.worker.read_batch(pending=False, block_ms=100)
    assert await _pending(rig) == 1 and vid not in rig.store.verdicts
    await rig.worker.reclaim()
    assert [d["final"] for d in pf.seen] == [False, False, True]
    assert rig.store.verdicts[vid]["degraded"] is False
    assert await _pending(rig) == 0


async def test_crashed_consumer_entry_is_reclaimed_by_another() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()), consumer="w2", reclaim_idle_ms=0)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    # A replica took the entry and died (container recreated under a new name).
    await rig.r.xreadgroup(keys.JOBS_GROUP, "worker-dead-replica", {keys.JOBS_STREAM: ">"}, count=1)
    assert await _pending(rig) == 1
    assert await rig.worker.reclaim() == 1
    assert rig.store.verdicts[vid]["final"] is True
    assert await _pending(rig) == 0


async def test_idle_threshold_respected() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()), reclaim_idle_ms=60_000)
    await rig.worker.ensure_group()
    await rig.submit(DEMO_BENIGN_URL)
    await rig.r.xreadgroup(keys.JOBS_GROUP, "busy-replica", {keys.JOBS_STREAM: ">"}, count=1)
    assert await rig.worker.reclaim() == 0  # still owned by a live consumer
    assert await _pending(rig) == 1


async def test_dead_letter_after_max_deliveries() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()), reclaim_idle_ms=0, max_deliveries=3)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    PublishFailure(rig)  # Redis publish permanently down
    await rig.worker.read_batch(pending=False, block_ms=100)  # delivery 1
    await rig.worker.reclaim()  # 2
    await rig.worker.reclaim()  # 3
    assert await _pending(rig) == 1 and await rig.r.xlen(keys.JOBS_DEAD) == 0
    await rig.worker.reclaim()  # 4 > 3: dead-letter + ack
    dead = await rig.r.xrange(keys.JOBS_DEAD)
    assert len(dead) == 1
    assert dead[0][1]["reason"].startswith("max_deliveries") and dead[0][1]["verdict_id"] == vid
    assert await _pending(rig) == 0


async def test_dead_letter_publishes_degraded_final_when_redis_recovers() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()), reclaim_idle_ms=0, max_deliveries=1)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    pf = PublishFailure(rig, n=1)
    await rig.worker.read_batch(pending=False, block_ms=100)  # delivery 1 fails
    await rig.worker.reclaim()  # delivery 2 > 1: give up with a degraded final
    finals = [d for d in pf.seen if d["final"]]
    assert len(finals) == 1 and finals[0]["degraded"] is True
    assert finals[0]["verdict"] == "suspicious"
    VERDICT.validate(finals[0])
    assert rig.store.verdicts[vid]["degraded"] is True
    fp = url_sha256(canonicalize(DEMO_BENIGN_URL))
    assert await rig.r.get(keys.verdict_cache(fp)) is None  # degraded never cached


async def test_cache_read_refuses_degraded_doc() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()))
    fp = "ab" * 32
    await rig.r.set(keys.verdict_cache(fp), "vd_01JC8Z9Q3M5N7P2R4T6V8W0XYZ")
    await rig.r.set(keys.last_key("vd_01JC8Z9Q3M5N7P2R4T6V8W0XYZ"), json.dumps({"final": True, "degraded": True}))
    cache = rig.worker.cascade.d.cache
    assert await cache.get(fp) is None


async def test_follower_event_keeps_leader_fingerprints() -> None:
    rig = Rig(SlowSandbox(phish_features(), delay_s=0.3))
    await rig.worker.ensure_group()
    v1 = await rig.submit(DEMO_LOOKALIKE_URL)
    v2 = await rig.submit(DEMO_LOOKALIKE_URL)
    await rig.worker.read_batch(pending=False, block_ms=100)
    events = {
        json.loads(f["event"])["verdict_id"]: json.loads(f["event"]) for _, f in await rig.r.xrange(keys.EVENTS_STREAM)
    }
    assert set(events) == {v1, v2}
    for ev in events.values():
        assert ev["payload"]["fingerprints"]["dom_simhash"] == "0x9f3a5c7e11223344"
        assert ev["event_id"] == "evt_" + ev["verdict_id"].removeprefix("vd_")
