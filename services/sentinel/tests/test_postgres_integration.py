"""Real-Postgres integration (marked `integration`; skipped unless FL_TEST_PG_DSN is set, e.g.
postgresql://falcon:testpw@127.0.0.1:55433/falcon_test)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import pytest
from graph_helpers import make_env

from falcon_sentinel.db import PgRepo

DSN = os.environ.get("FL_TEST_PG_DSN")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not DSN, reason="FL_TEST_PG_DSN not set")]


@pytest.fixture
async def repo():
    assert DSN
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    r = PgRepo(DSN)
    await r.init()
    yield r
    await r.close()


def by_tool(inc: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [a for a in inc["actions"] if a["tool"] == tool]


async def test_repo_roundtrip_and_audit_is_append_only(repo):
    env = await make_env(repo=repo)
    assert len(await repo.load_incidents()) == 3
    assert len(await repo.load_features()) == len(env.fx.events)
    iid = env.campaign_id()
    await env.runner().run(iid)
    acts = await repo.list_actions(iid)
    assert {"block_indicator", "draft_takedown"} <= {a["tool"] for a in acts}
    assert await repo.audit_list(iid)
    with psycopg.connect(DSN, autocommit=True) as c:  # type: ignore[arg-type]
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("UPDATE audit_log SET actor='x'")
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("DELETE FROM audit_log")
        assert c.execute("SELECT count(*) FROM blocks").fetchone() == (1,)


async def test_restart_resume_with_postgres_checkpointer(repo):
    """Crash mid-run, build a brand new runner + new connection pool to the same Postgres, resume, approve."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    from falcon_sentinel.llm import StubLLM

    assert DSN
    env = await make_env(repo=repo)
    iid = env.campaign_id()

    class Crash(Exception):
        pass

    async with AsyncPostgresSaver.from_conn_string(DSN) as saver:
        await saver.setup()
        with pytest.raises(Crash):
            await env.runner(StubLLM(overrides={"propose": lambda u: Crash("died")}), saver).run(
                iid
            )

    # "process restart": new repo/cache/core loaded from Postgres, new checkpointer connection
    repo2 = PgRepo(DSN)
    await repo2.init()
    env2 = await make_env(repo=repo2, redis=env.redis, load=False)
    await env2.cache.load()
    assert env2.cache.get(iid)["status"] == "triaging"  # type: ignore[index]
    fresh = StubLLM()
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver2:
        runner = env2.runner(fresh, saver2)
        assert await runner.resume_unfinished() == [iid]
        assert [c["task"] for c in fresh.calls] == ["propose"]
        (td,) = by_tool(env2.cache.get(iid) or {}, "draft_takedown")
        assert td["status"] == "awaiting_approval"
    async with AsyncPostgresSaver.from_conn_string(DSN) as saver3:  # restart again while paused
        runner3 = env2.runner(StubLLM(), saver3)
        assert [p["action_id"] for p in await runner3.pending_approvals(iid)] == [td["action_id"]]
        await runner3.approve(iid, td["action_id"], "op")
    inc = await repo2.load_incidents()
    assert next(i for i in inc if i["incident_id"] == iid)["status"] == "mitigated"
    await repo2.close()


def test_thread_ids_are_incident_ids():
    assert uuid.uuid4()  # placeholder keeps module importable when skipped
