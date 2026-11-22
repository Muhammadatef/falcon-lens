"""Persistence: Postgres repo (incidents, incident_actions, sentinel_features, audit_log, blocks), an
in-memory twin for unit tests, and a write-through incident cache that the deterministic core and the
tools share (so restarts rehydrate and the graph and the consumer never disagree)."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sentinel_core.events import parse_time
from sentinel_core.incidents import InMemoryIncidentStore, validate_incident

DDL = """
CREATE TABLE IF NOT EXISTS incidents (
  incident_id text PRIMARY KEY,
  type text NOT NULL, severity text NOT NULL, status text NOT NULL,
  brand_id text, source text NOT NULL,
  doc jsonb NOT NULL,
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS incidents_status_idx ON incidents (status);
CREATE TABLE IF NOT EXISTS incident_actions (
  action_id text PRIMARY KEY,
  incident_id text NOT NULL, tool text NOT NULL, mode text NOT NULL, status text NOT NULL,
  doc jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS incident_actions_inc_idx ON incident_actions (incident_id);
CREATE TABLE IF NOT EXISTS sentinel_features (
  event_id text PRIMARY KEY, type text NOT NULL, occurred_at timestamptz NOT NULL, doc jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS sentinel_features_time_idx ON sentinel_features (occurred_at);
CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL, actor text NOT NULL, incident_id text, action_id text,
  tool text NOT NULL, mode text NOT NULL, args jsonb NOT NULL, result jsonb NOT NULL,
  evidence_ids jsonb NOT NULL
);
CREATE OR REPLACE FUNCTION fl_audit_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_immutable ON audit_log;
CREATE TRIGGER audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION fl_audit_immutable();
CREATE TABLE IF NOT EXISTS blocks (
  action_id text PRIMARY KEY, incident_id text NOT NULL, kind text NOT NULL,
  value_defanged text NOT NULL, sha256 text NOT NULL, redis_key text NOT NULL,
  blocked_at timestamptz NOT NULL, expires_at timestamptz NOT NULL, reverted_at timestamptz
);
"""


class Repo(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...
    async def load_incidents(self) -> list[dict[str, Any]]: ...
    async def save_incident(self, inc: dict[str, Any]) -> None: ...
    async def delete_incident(self, incident_id: str) -> None: ...
    async def add_features(self, events: list[dict[str, Any]]) -> None: ...
    async def load_features(self) -> list[dict[str, Any]]: ...
    async def query_features(self, since: datetime | None, limit: int) -> list[dict[str, Any]]: ...
    async def audit_append(self, entry: dict[str, Any]) -> int: ...
    async def audit_list(self, incident_id: str | None = None) -> list[dict[str, Any]]: ...
    async def block_put(self, block: dict[str, Any]) -> None: ...
    async def block_get(self, action_id: str) -> dict[str, Any] | None: ...
    async def block_revert(self, action_id: str, at: datetime) -> None: ...
    async def list_actions(self, incident_id: str) -> list[dict[str, Any]]: ...


class MemoryRepo:
    """Unit-test twin of PgRepo (same semantics, including append-only audit)."""

    def __init__(self) -> None:
        self.incidents: dict[str, dict[str, Any]] = {}
        self.features: dict[str, dict[str, Any]] = {}
        self.audit: list[dict[str, Any]] = []
        self.blocks: dict[str, dict[str, Any]] = {}
        self.actions: dict[str, dict[str, Any]] = {}

    async def init(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def load_incidents(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(v) for _, v in sorted(self.incidents.items())]

    async def save_incident(self, inc: dict[str, Any]) -> None:
        self.incidents[inc["incident_id"]] = copy.deepcopy(inc)
        for a in inc["actions"]:
            self.actions[a["action_id"]] = {"incident_id": inc["incident_id"], **copy.deepcopy(a)}

    async def delete_incident(self, incident_id: str) -> None:
        self.incidents.pop(incident_id, None)

    async def add_features(self, events: list[dict[str, Any]]) -> None:
        for e in events:
            self.features.setdefault(e["event_id"], copy.deepcopy(e))

    async def load_features(self) -> list[dict[str, Any]]:
        return sorted(self.features.values(), key=lambda e: (e["occurred_at"], e["event_id"]))

    async def query_features(self, since: datetime | None, limit: int) -> list[dict[str, Any]]:
        rows = await self.load_features()
        if since:
            rows = [r for r in rows if parse_time(r["occurred_at"]) >= since]
        return list(reversed(rows))[:limit]

    async def audit_append(self, entry: dict[str, Any]) -> int:
        self.audit.append(copy.deepcopy(entry))
        return len(self.audit)

    async def audit_list(self, incident_id: str | None = None) -> list[dict[str, Any]]:
        return [a for a in self.audit if incident_id in (None, a.get("incident_id"))]

    async def block_put(self, block: dict[str, Any]) -> None:
        self.blocks[block["action_id"]] = {**block, "reverted_at": None}

    async def block_get(self, action_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.blocks.get(action_id))

    async def block_revert(self, action_id: str, at: datetime) -> None:
        self.blocks[action_id]["reverted_at"] = at

    async def list_actions(self, incident_id: str) -> list[dict[str, Any]]:
        return [a for a in self.actions.values() if a["incident_id"] == incident_id]


class PgRepo:
    def __init__(self, dsn: str) -> None:
        from psycopg_pool import AsyncConnectionPool

        self.dsn = dsn
        self.pool = AsyncConnectionPool(dsn, min_size=1, max_size=5, open=False, kwargs={"autocommit": True})

    async def init(self) -> None:
        await self.pool.open()
        async with self.pool.connection() as c:
            await c.execute(DDL)  # type: ignore[call-overload]

    async def close(self) -> None:
        await self.pool.close()

    async def load_incidents(self) -> list[dict[str, Any]]:
        async with self.pool.connection() as c:
            cur = await c.execute("SELECT doc FROM incidents ORDER BY incident_id")
            return [r[0] for r in await cur.fetchall()]

    async def save_incident(self, inc: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as c, c.transaction():
            await c.execute(
                "INSERT INTO incidents (incident_id,type,severity,status,brand_id,source,doc,created_at,updated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (incident_id) DO UPDATE SET"
                " severity=EXCLUDED.severity,status=EXCLUDED.status,brand_id=EXCLUDED.brand_id,"
                " doc=EXCLUDED.doc,updated_at=EXCLUDED.updated_at",
                (
                    inc["incident_id"],
                    inc["type"],
                    inc["severity"],
                    inc["status"],
                    inc.get("brand_id"),
                    inc["source"],
                    Jsonb(inc),
                    parse_time(inc["created_at"]),
                    parse_time(inc["updated_at"]),
                ),
            )
            for a in inc["actions"]:
                await c.execute(
                    "INSERT INTO incident_actions (action_id,incident_id,tool,mode,status,doc) VALUES (%s,%s,%s,%s,%s,%s)"
                    " ON CONFLICT (action_id) DO UPDATE SET status=EXCLUDED.status,doc=EXCLUDED.doc,updated_at=now()",
                    (
                        a["action_id"],
                        inc["incident_id"],
                        a["tool"],
                        a["mode"],
                        a["status"],
                        Jsonb(a),
                    ),
                )

    async def delete_incident(self, incident_id: str) -> None:
        async with self.pool.connection() as c, c.transaction():
            await c.execute("DELETE FROM incident_actions WHERE incident_id=%s", (incident_id,))
            await c.execute("DELETE FROM incidents WHERE incident_id=%s", (incident_id,))

    async def add_features(self, events: list[dict[str, Any]]) -> None:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as c, c.transaction():
            for e in events:
                await c.execute(
                    "INSERT INTO sentinel_features (event_id,type,occurred_at,doc) VALUES (%s,%s,%s,%s)"
                    " ON CONFLICT (event_id) DO NOTHING",
                    (e["event_id"], e["type"], parse_time(e["occurred_at"]), Jsonb(e)),
                )

    async def load_features(self) -> list[dict[str, Any]]:
        async with self.pool.connection() as c:
            cur = await c.execute("SELECT doc FROM sentinel_features ORDER BY occurred_at, event_id")
            return [r[0] for r in await cur.fetchall()]

    async def query_features(self, since: datetime | None, limit: int) -> list[dict[str, Any]]:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT doc FROM sentinel_features WHERE (%s::timestamptz IS NULL OR occurred_at >= %s)"
                " ORDER BY occurred_at DESC LIMIT %s",
                (since, since, limit),
            )
            return [r[0] for r in await cur.fetchall()]

    async def audit_append(self, entry: dict[str, Any]) -> int:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as c:
            cur = await c.execute(
                "INSERT INTO audit_log (at,actor,incident_id,action_id,tool,mode,args,result,evidence_ids)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    entry["at"],
                    entry["actor"],
                    entry.get("incident_id"),
                    entry.get("action_id"),
                    entry["tool"],
                    entry["mode"],
                    Jsonb(entry["args"]),
                    Jsonb(entry["result"]),
                    Jsonb(entry["evidence_ids"]),
                ),
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def audit_list(self, incident_id: str | None = None) -> list[dict[str, Any]]:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT at,actor,incident_id,action_id,tool,mode,args,result,evidence_ids FROM audit_log"
                " WHERE (%s::text IS NULL OR incident_id=%s) ORDER BY id",
                (incident_id, incident_id),
            )
            cols = [
                "at",
                "actor",
                "incident_id",
                "action_id",
                "tool",
                "mode",
                "args",
                "result",
                "evidence_ids",
            ]
            return [dict(zip(cols, r, strict=True)) for r in await cur.fetchall()]

    async def block_put(self, block: dict[str, Any]) -> None:
        async with self.pool.connection() as c:
            await c.execute(
                "INSERT INTO blocks (action_id,incident_id,kind,value_defanged,sha256,redis_key,blocked_at,expires_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (action_id) DO NOTHING",
                (
                    block["action_id"],
                    block["incident_id"],
                    block["kind"],
                    block["value_defanged"],
                    block["sha256"],
                    block["redis_key"],
                    block["blocked_at"],
                    block["expires_at"],
                ),
            )

    async def block_get(self, action_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT action_id,incident_id,kind,value_defanged,sha256,redis_key,blocked_at,expires_at,reverted_at"
                " FROM blocks WHERE action_id=%s",
                (action_id,),
            )
            r = await cur.fetchone()
            if r is None:
                return None
            cols = [
                "action_id",
                "incident_id",
                "kind",
                "value_defanged",
                "sha256",
                "redis_key",
                "blocked_at",
                "expires_at",
                "reverted_at",
            ]
            return dict(zip(cols, r, strict=True))

    async def block_revert(self, action_id: str, at: datetime) -> None:
        async with self.pool.connection() as c:
            await c.execute("UPDATE blocks SET reverted_at=%s WHERE action_id=%s", (at, action_id))

    async def list_actions(self, incident_id: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT doc FROM incident_actions WHERE incident_id=%s ORDER BY action_id",
                (incident_id,),
            )
            return [r[0] for r in await cur.fetchall()]


class IncidentCache(InMemoryIncidentStore):
    """Write-through cache: the core and the tools mutate it synchronously, `flush()` persists the diff."""

    def __init__(self, repo: Repo) -> None:
        super().__init__()
        self.repo = repo
        self._flushed: dict[str, str] = {}

    @staticmethod
    def _fp(inc: dict[str, Any]) -> str:
        return json.dumps(inc, sort_keys=True, default=str)

    async def load(self) -> int:
        for inc in await self.repo.load_incidents():
            super().put(inc)
            self._flushed[inc["incident_id"]] = self._fp(inc)
        return len(self._flushed)

    def update(self, incident_id: str, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        inc = self.get(incident_id)
        if inc is None:
            raise KeyError(incident_id)
        fn(inc)
        inc["updated_at"] = max(inc["updated_at"], datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        validate_incident(inc)
        super().put(inc)
        return inc

    async def flush(self) -> tuple[list[str], list[str]]:
        """Returns (ids written, ids deleted)."""
        current = {i["incident_id"]: i for i in self.all()}
        written, deleted = [], []
        for iid, inc in current.items():
            fp = self._fp(inc)
            if self._flushed.get(iid) != fp:
                await self.repo.save_incident(inc)
                self._flushed[iid] = fp
                written.append(iid)
        for iid in [i for i in self._flushed if i not in current]:
            await self.repo.delete_incident(iid)
            del self._flushed[iid]
            deleted.append(iid)
        return written, deleted
