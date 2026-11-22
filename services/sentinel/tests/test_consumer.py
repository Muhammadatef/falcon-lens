from __future__ import annotations

import json

from graph_helpers import make_consumer, make_env, publish
from sentinel_core.events import parse_event

from falcon_sentinel.consumer import DLQ, GROUP, STREAM


async def test_consumer_turns_planted_replay_into_one_campaign_and_persists():
    env = await make_env(load=False)
    seen: list[list[str]] = []

    async def hook(ids: list[str]) -> None:
        seen.append(ids)

    c = make_consumer(env, on_incidents=hook)
    await c.setup()
    await publish(env.redis, env.fx.events)
    n = 0
    while True:
        done = await c.run_once(block_ms=10, count=100)
        if not done:
            break
        n += done
    assert n == len(env.fx.events)
    camps = [i for i in env.cache.all() if i["type"] == "campaign"]
    assert len(camps) == 1 and len(env.cache.all()) == 3
    assert {i["incident_id"] for i in await env.repo.load_incidents()} == {i["incident_id"] for i in env.cache.all()}
    assert len(await env.repo.load_features()) == len(env.fx.events)
    assert (await env.redis.xpending(STREAM, GROUP))["pending"] == 0
    assert any(camps[0]["incident_id"] in ids for ids in seen)


async def test_idempotent_on_event_id_duplicates():
    env = await make_env(load=False)
    c = make_consumer(env)
    await c.setup()
    await publish(env.redis, env.fx.events + env.fx.events)  # every event delivered twice
    while await c.run_once(block_ms=10, count=100):
        pass
    assert len(env.cache.all()) == 3 and len(await env.repo.load_features()) == len(env.fx.events)


async def test_restart_rehydrates_from_persistence_without_changes():
    env = await make_env(load=False)
    c = make_consumer(env)
    await c.setup()
    await publish(env.redis, env.fx.events)
    while await c.run_once(block_ms=10, count=100):
        pass
    before = env.cache.all()
    # new process: fresh cache + core over the same repo (Postgres) and the same Redis
    env2 = await make_env(repo=env.repo, redis=env.redis, load=False)
    c2 = make_consumer(env2, "c2")
    assert await c2.setup() == len(env.fx.events)
    assert env2.cache.all() == before
    assert (await env2.cache.flush()) == ([], [])  # nothing re-written: state converged


async def test_dlq_after_three_failures_and_ack():
    env = await make_env(load=False)
    c = make_consumer(env)
    await c.setup()
    await env.redis.xadd(STREAM, {"event": '{"event_id": "bad"}'})
    await env.redis.xadd(STREAM, {"event": "not json"})
    await publish(env.redis, env.fx.events[:3])
    for _ in range(4):
        await c.run_once(block_ms=10, count=100)
    dlq = await env.redis.xrange(DLQ)
    assert len(dlq) == 2 and all(f["attempts"] == "3" and f["error"] for _, f in dlq)
    assert (await env.redis.xpending(STREAM, GROUP))["pending"] == 0
    assert len(await env.repo.load_features()) == 3  # good events after the poison pills still processed


async def test_failed_attempts_below_three_stay_pending():
    env = await make_env(load=False)
    c = make_consumer(env)
    await c.setup()
    await env.redis.xadd(STREAM, {"event": "garbage"})
    await c.run_once(block_ms=10)
    await c.run_once(block_ms=10)
    assert (await env.redis.xpending(STREAM, GROUP))["pending"] == 1 and await env.redis.xlen(DLQ) == 0


async def test_stale_pending_claimed_by_another_consumer():
    env = await make_env(load=False)
    dead = make_consumer(env, "dead")
    await dead.setup()
    await publish(env.redis, env.fx.events[:5])
    await env.redis.xreadgroup(GROUP, "dead", {STREAM: ">"}, count=10)  # read, never acked: consumer died
    assert (await env.redis.xpending(STREAM, GROUP))["pending"] == 5
    alive = make_consumer(env, "alive")
    assert await alive.claim_stale() == 5
    assert (await env.redis.xpending(STREAM, GROUP))["pending"] == 0
    assert {e["event_id"] for e in await env.repo.load_features()} == {e["event_id"] for e in env.fx.events[:5]}


def test_fixture_events_parse():
    assert all(parse_event(json.loads(json.dumps(e))) for e in make_fx())


def make_fx():
    from sentinel_core.fixtures import generate

    return generate().events
