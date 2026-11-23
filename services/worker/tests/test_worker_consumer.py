"""Worker against fakeredis: message formats (docs/CONTRACTS.md), idempotency, single-flight."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import fakeredis
import pytest
from jsonschema import Draft202012Validator
from prometheus_client import CollectorRegistry
from referencing import Registry
from referencing.jsonschema import DRAFT202012

from falcon_core.cascade import (
    Cascade,
    CascadeDeps,
    CascadeMetrics,
    CheckJob,
    SandboxClient,
    StubSandboxClient,
    new_verdict_id,
)
from falcon_core.cascade.engine import url_sha256
from falcon_core.cascade.testing import (
    DEMO_BENIGN_URL,
    DEMO_LOOKALIKE_URL,
    DEMO_OFFICIAL_URL,
    FIXTURE_POLICY,
    SlowSandbox,
    benign_features,
    official_features,
    phish_features,
    stub_resolver,
)
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.cache import RedisCache
from falcon_core.signals.reputation.mirror import SET_KEY, UPDATED_KEY, FeedMirror
from falcon_core.signals.url.canonical import canonicalize
from falcon_worker import keys
from falcon_worker.consumer import RedisVerdictCache, Worker
from falcon_worker.store import MemoryStore, migration_sql

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def _validator(name: str) -> Draft202012Validator:
    resources = []
    for path in CONTRACTS.glob("*.schema.json"):
        schema = json.loads(path.read_text())
        resources.append((schema["$id"], DRAFT202012.create_resource(schema)))
    registry: Registry[Any] = Registry().with_resources(resources)
    return Draft202012Validator(json.loads((CONTRACTS / f"{name}.schema.json").read_text()), registry=registry)


VERDICT = _validator("verdict")
EVENT = _validator("event")


class Rig:
    def __init__(self, sandbox: SandboxClient, **wkw: Any) -> None:
        self.server = fakeredis.FakeServer()
        self.r: Any = fakeredis.FakeAsyncRedis(server=self.server, decode_responses=True)
        self.store = MemoryStore()
        self.metrics = CascadeMetrics(CollectorRegistry())
        registry = default_registry()
        self.sandbox = sandbox
        deps = CascadeDeps(
            registry=registry,
            sandbox=sandbox,
            metrics=self.metrics,
            cache=RedisVerdictCache(self.r, self.store),
            guard_policy=FIXTURE_POLICY,
            resolver=stub_resolver,
            signal_cache=RedisCache(self.r),
            mirror=FeedMirror(RedisCache(self.r)),  # the production hash-only mirror, on fakeredis
        )
        # Mirror loaded 10 min ago and empty (the refresh job's state); tests add entries like smoke.
        self.r_sync_updated = time.time() - 600
        wkw.setdefault("consumer", "w1")
        self.worker = Worker(self.r, Cascade(deps), self.store, registry, self.metrics, poll_s=0.02, **wkw)

    async def submit(self, url: str, input_type: str = "url", **payload: Any) -> str:
        if not await self.r.exists(UPDATED_KEY):
            await self.r.set(UPDATED_KEY, json.dumps(self.r_sync_updated))
        vid = new_verdict_id()
        c = canonicalize(url)
        body: dict[str, Any] = {"url": url, "canonical_sha256": url_sha256(c)} if url else {}
        body.update(payload)
        job = CheckJob(verdict_id=vid, input_type=input_type, payload=body)
        await self.r.xadd(keys.JOBS_STREAM, job.to_fields())
        return vid


async def _collect(r: Any, vid: str, out: list[dict[str, Any]]) -> None:
    ps = r.pubsub()
    await ps.subscribe(keys.channel(vid))
    while True:
        msg = await ps.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if msg is not None:
            doc = json.loads(msg["data"])
            out.append(doc)
            if doc["final"]:
                break


async def test_url_job_publishes_partials_final_store_event_cache() -> None:
    rig = Rig(StubSandboxClient(default=phish_features()))
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_LOOKALIKE_URL)
    msgs: list[dict[str, Any]] = []
    listener = asyncio.create_task(_collect(rig.r, vid, msgs))
    await asyncio.sleep(0.05)
    assert await rig.worker.read_batch(pending=False, block_ms=100) == 1
    await asyncio.wait_for(listener, 2)

    assert [m["tier_reached"] for m in msgs] == ["T0", "T1", "T2"]
    assert [m["final"] for m in msgs] == [False, False, True]
    for m in msgs:
        VERDICT.validate(m)
        assert m["verdict_id"] == vid
    final = msgs[-1]
    assert final["verdict"] == "dangerous"
    assert any(e.get("hard_rule") == "H1" for e in final["evidence"])

    assert json.loads(await rig.r.get(keys.last_key(vid))) == final
    assert 0 < await rig.r.ttl(keys.last_key(vid)) <= keys.LAST_TTL_S
    assert rig.store.verdicts[vid] == final
    assert {k[1] for k in rig.store.evidence if k[0] == vid} == {e["id"] for e in final["evidence"]}

    fp = url_sha256(canonicalize(DEMO_LOOKALIKE_URL))
    assert await rig.r.get(keys.verdict_cache(fp)) == vid
    assert 23 * 3600 < await rig.r.ttl(keys.verdict_cache(fp)) <= 24 * 3600

    events = await rig.r.xrange(keys.EVENTS_STREAM)
    assert len(events) == 1
    _, fields = events[0]
    assert list(fields) == ["event"]
    ev = json.loads(fields["event"])
    EVENT.validate(ev)
    assert ev["type"] == "verdict.created" and ev["verdict_id"] == vid
    p = ev["payload"]
    assert p["verdict"] == "dangerous" and p["brand_id"] == "falcon_demo_bank"
    assert p["registrable_domain"] == "falcon-demo-bank-login[.]test"
    assert p["fingerprints"]["dom_simhash"] == "0x9f3a5c7e11223344"
    assert "brand.claimed_not_owned" in p["top_signals"]
    blob = json.dumps(ev)
    assert "Welcome to" not in blob and "Online Banking" not in blob  # no raw page text

    pending = await rig.r.xpending(keys.JOBS_STREAM, keys.JOBS_GROUP)
    assert pending["pending"] == 0
    assert (
        rig.metrics.registry.get_sample_value(
            "fl_checks_total",
            {"input_type": "url", "verdict": "dangerous", "tier": "T2", "route": "none",
             "source": "live"},
        )
        == 1
    )  # fmt: skip


async def test_official_job_no_warning_signs() -> None:
    rig = Rig(StubSandboxClient(default=official_features()))
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_OFFICIAL_URL)
    await rig.worker.read_batch(pending=False, block_ms=100)
    final = rig.store.verdicts[vid]
    VERDICT.validate(final)
    assert final["verdict"] == "no_warning_signs" and final["actions"]["caution"]["en"]


async def test_duplicate_entry_is_processed_once() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    rig = Rig(sandbox)
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    entries = await rig.r.xrange(keys.JOBS_STREAM)
    fields = entries[0][1]
    await rig.r.xadd(keys.JOBS_STREAM, fields)  # API retried the XADD
    await rig.worker.read_batch(pending=False, block_ms=100)
    assert len(sandbox.calls) == 1
    assert len(await rig.r.xrange(keys.EVENTS_STREAM)) == 1
    assert rig.store.verdicts[vid]["final"] is True
    # Redelivery of the same entry after it finished: acked, not re-run.
    first = await rig.worker.handle(entries[0][0], fields)
    assert first is None and len(sandbox.calls) == 1


async def test_single_flight_two_concurrent_identical_checks_share_one_run() -> None:
    sandbox = SlowSandbox(phish_features(), delay_s=0.3)
    rig = Rig(sandbox)
    await rig.worker.ensure_group()
    v1 = await rig.submit(DEMO_LOOKALIKE_URL)
    v2 = await rig.submit(DEMO_LOOKALIKE_URL)
    assert await rig.worker.read_batch(pending=False, block_ms=100) == 2
    assert sandbox.calls == 1
    d1, d2 = rig.store.verdicts[v1], rig.store.verdicts[v2]
    VERDICT.validate(d1)
    VERDICT.validate(d2)
    assert d1["verdict"] == d2["verdict"] == "dangerous"
    assert d1["evidence"] == d2["evidence"]
    assert json.loads(await rig.r.get(keys.last_key(v2)))["final"] is True
    assert rig.metrics.registry.get_sample_value("fl_cache_hits_total", {"layer": "single_flight"}) == 1
    # Lock released by the leader.
    fp = url_sha256(canonicalize(DEMO_LOOKALIKE_URL))
    assert await rig.r.get(keys.worker_single_flight(fp)) is None


async def test_single_flight_across_two_workers() -> None:
    sandbox = SlowSandbox(phish_features(), delay_s=0.3)
    rig = Rig(sandbox)
    other = Worker(rig.r, rig.worker.cascade, rig.store, default_registry(), rig.metrics,
                   consumer="w2", poll_s=0.02)  # fmt: skip
    await rig.worker.ensure_group()
    v1 = await rig.submit(DEMO_LOOKALIKE_URL)
    v2 = await rig.submit(DEMO_LOOKALIKE_URL)
    entries = await rig.r.xrange(keys.JOBS_STREAM)
    await asyncio.gather(rig.worker.handle(*entries[0]), other.handle(*entries[1]))
    assert sandbox.calls == 1
    assert rig.store.verdicts[v1]["verdict"] == rig.store.verdicts[v2]["verdict"]


async def test_cache_hit_on_second_check() -> None:
    sandbox = StubSandboxClient(default=phish_features())
    rig = Rig(sandbox)
    await rig.worker.ensure_group()
    await rig.submit(DEMO_LOOKALIKE_URL)
    await rig.worker.read_batch(pending=False, block_ms=100)
    v2 = await rig.submit(DEMO_LOOKALIKE_URL)
    await rig.worker.read_batch(pending=False, block_ms=100)
    assert len(sandbox.calls) == 1
    VERDICT.validate(rig.store.verdicts[v2])
    assert rig.metrics.registry.get_sample_value("fl_cache_hits_total", {"layer": "verdict"}) == 1


async def test_message_job_runs_the_message_pipeline_with_h5() -> None:
    rig = Rig(StubSandboxClient(default=phish_features()))
    await rig.worker.ensure_group()
    vid = await rig.submit(
        "", input_type="message", text=f"Verify your account: {DEMO_LOOKALIKE_URL}", sha256="ab" * 32
    )
    await rig.worker.read_batch(pending=False, block_ms=100)
    doc = rig.store.verdicts[vid]
    VERDICT.validate(doc)
    assert doc["final"] and doc["input_type"] == "message" and doc["verdict"] == "dangerous"
    assert any(e.get("hard_rule") == "H5" for e in doc["evidence"])
    assert not doc["degraded"]


async def test_email_job_reads_the_blob_and_clears_it() -> None:
    import base64

    eml = (
        b"From: Falcon Demo Bank <alerts@falcon-demo-bank-login.test>\r\nTo: u@example.test\r\n"
        b"Subject: Verify\r\nContent-Type: text/plain\r\n\r\nSign in: " + DEMO_LOOKALIKE_URL.encode() + b"\r\n"
    )
    rig = Rig(StubSandboxClient(default=phish_features()))
    await rig.worker.ensure_group()
    vid = await rig.submit("", input_type="email", sha256="cd" * 32)
    await rig.r.set(keys.blob_key(vid), base64.b64encode(eml).decode(), ex=600)
    await rig.worker.read_batch(pending=False, block_ms=100)
    doc = rig.store.verdicts[vid]
    VERDICT.validate(doc)
    assert doc["input_type"] == "email" and doc["verdict"] == "dangerous"
    assert await rig.r.get(keys.blob_key(vid)) is None


@pytest.mark.parametrize("input_type", ["message", "image"])  # the API rejects non-.eml uploads
async def test_missing_or_garbage_input_is_degraded_never_safe(input_type: str) -> None:
    rig = Rig(StubSandboxClient(error="unused"))
    await rig.worker.ensure_group()
    vid = await rig.submit("", input_type=input_type, sha256="ab" * 32)
    if input_type != "message":
        await rig.r.set(keys.blob_key(vid), "aGVsbG8=", ex=600)  # "hello": not an image
    await rig.worker.read_batch(pending=False, block_ms=100)
    doc = rig.store.verdicts[vid]
    VERDICT.validate(doc)
    assert doc["final"] and doc["degraded"] and doc["verdict"] == "suspicious"
    assert doc["input_type"] == input_type


async def test_malformed_job_goes_to_dead_letter_and_is_acked() -> None:
    rig = Rig(StubSandboxClient(error="unused"))
    await rig.worker.ensure_group()
    await rig.r.xadd(keys.JOBS_STREAM, {"verdict_id": "nope", "payload_json": "{"})
    await rig.worker.read_batch(pending=False, block_ms=100)
    assert len(await rig.r.xrange(keys.JOBS_DEAD)) == 1
    assert (await rig.r.xpending(keys.JOBS_STREAM, keys.JOBS_GROUP))["pending"] == 0


async def test_pending_entries_are_retried_after_restart() -> None:
    rig = Rig(StubSandboxClient(default=benign_features()))
    await rig.worker.ensure_group()
    vid = await rig.submit(DEMO_BENIGN_URL)
    # Simulate a crash: the entry was delivered to w1 but never acked.
    await rig.r.xreadgroup(keys.JOBS_GROUP, "w1", {keys.JOBS_STREAM: ">"}, count=1)
    assert await rig.worker.read_batch(pending=True) == 1
    assert rig.store.verdicts[vid]["final"] is True


def test_entries_parser_accepts_resp3_shape() -> None:
    resp3 = {"fl:jobs": [["1-0", {"verdict_id": "vd_X"}]]}
    resp2 = [["fl:jobs", [("1-0", {"verdict_id": "vd_X"})]]]
    assert Worker._entries(resp3) == Worker._entries(resp2) == [("1-0", {"verdict_id": "vd_X"})]


def test_migration_matches_api_contract() -> None:
    sql = "\n".join(migration_sql())
    assert "CREATE TABLE IF NOT EXISTS verdicts" in sql
    assert "verdict_id text PRIMARY KEY" in sql and "doc        jsonb NOT NULL" in sql
    assert "CREATE TABLE IF NOT EXISTS evidence" in sql


def test_job_fields_roundtrip() -> None:
    vid = new_verdict_id()
    job = CheckJob(verdict_id=vid, payload={"url": "https://x.test/", "canonical_sha256": "ab"})
    back = CheckJob.from_fields(job.to_fields())
    assert back.url == "https://x.test/" and back.fingerprint == "ab" and back.verdict_id == vid
    with pytest.raises(ValueError):
        CheckJob.from_fields({"verdict_id": "vd_bad", "payload_json": "{}"})


async def test_smoke_check3_synthetic_feed_entry_is_h2_at_t0() -> None:
    """What `make smoke` check 3 does: SADD sha256(canonical URL) + sha256(host), fresh updated_at."""
    sandbox = StubSandboxClient(error="must_not_render")
    rig = Rig(sandbox)
    await rig.worker.ensure_group()
    url = "http://synthetic-openphish.test/ab12cd34"
    hashes = [hashlib.sha256(x.encode()).hexdigest() for x in (url, "synthetic-openphish.test")]
    await rig.r.sadd(SET_KEY, *hashes)
    await rig.r.set(UPDATED_KEY, json.dumps(time.time() - 60))
    vid = await rig.submit(url)
    await rig.worker.read_batch(pending=False, block_ms=100)
    final = rig.store.verdicts[vid]
    VERDICT.validate(final)
    assert final["verdict"] == "dangerous" and final["tier_reached"] == "T0"
    assert any(e.get("hard_rule") == "H2" and e["tier"] == "T0" for e in final["evidence"])
    assert sandbox.calls == []


async def test_stale_mirror_entry_is_not_h2() -> None:
    rig = Rig(StubSandboxClient(default=benign_features("http://synthetic-openphish.test/x")))
    await rig.worker.ensure_group()
    url = "http://synthetic-openphish.test/x"
    await rig.r.sadd(SET_KEY, hashlib.sha256(url.encode()).hexdigest())
    await rig.r.set(UPDATED_KEY, json.dumps(time.time() - 7 * 3600))
    vid = await rig.submit(url)
    await rig.worker.read_batch(pending=False, block_ms=100)
    final = rig.store.verdicts[vid]
    assert not any(e.get("hard_rule") == "H2" for e in final["evidence"])
