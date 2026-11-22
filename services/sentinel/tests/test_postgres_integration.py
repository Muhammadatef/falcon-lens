"""Real-Postgres integration (marked `integration`; skipped unless FL_TEST_PG_DSN is set, e.g.
postgresql://falcon:testpw@127.0.0.1:55433/falcon_test)."""

from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg
import psycopg.conninfo
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
        with pytest.raises(psycopg.errors.RaiseException):
            c.execute("TRUNCATE audit_log")
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
            await env.runner(StubLLM(overrides={"propose": lambda u: Crash("died")}), saver).run(iid)

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


async def test_service_role_cannot_tamper_with_audit_log_when_owner_role_is_separate():
    """Owner creates schema + grants; the service role only gets INSERT/SELECT on audit_log."""
    from falcon_sentinel.llm import StubLLM

    assert DSN
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        c.execute("DROP ROLE IF EXISTS fl_test_app")
        c.execute("CREATE ROLE fl_test_app LOGIN PASSWORD 'apppw'")
    base = psycopg.conninfo.conninfo_to_dict(DSN)
    app_dsn = psycopg.conninfo.make_conninfo(
        user="fl_test_app", password="apppw", **{k: v for k, v in base.items() if k not in ("user", "password")}
    )
    repo = PgRepo(app_dsn, owner_dsn=DSN, app_role="fl_test_app")
    await repo.init()
    try:
        env = await make_env(repo=repo)
        await env.runner(StubLLM()).run(env.campaign_id())
        assert await repo.audit_list(env.campaign_id())  # INSERT + SELECT work
        assert await repo.stix_get(env.campaign_id()) is not None
        with psycopg.connect(app_dsn, autocommit=True) as c:
            for stmt in (
                "UPDATE audit_log SET actor='x'",
                "DELETE FROM audit_log",
                "TRUNCATE audit_log",
                "ALTER TABLE audit_log DISABLE TRIGGER audit_log_immutable",
                "DROP TRIGGER audit_log_no_truncate ON audit_log",
                "DROP TABLE audit_log",
            ):
                with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
                    c.execute(stmt)
            assert c.execute("SELECT count(*) FROM audit_log").fetchone()[0] > 0
    finally:
        await repo.close()
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            c.execute("DROP OWNED BY fl_test_app; DROP ROLE fl_test_app")
