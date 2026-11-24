"""Hunt persistence: hunt_candidates, hunt_source_state, hunt_quota, hunt_cycles (migrations/002_hunt.sql).

``MemoryHuntStore`` for unit tests, ``PgHuntStore`` for the service. The table is the authority for "is this
verdict a hunt verdict": the consumer looks verdict_ids up here and never trusts payload.channel.
A Postgres advisory lock makes sure two Sentinel replicas never run a hunt cycle at the same time.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import Counter
from dataclasses import fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sentinel_core.hunt.candidates import Candidate

MIGRATION = Path(
    os.environ.get("FL_HUNT_MIGRATION") or Path(__file__).resolve().parents[3] / "migrations" / "002_hunt.sql"
)
LOCK_KEY = 0x464C48554E54  # "FLHUNT"
GRANTS = "GRANT SELECT, INSERT, UPDATE ON hunt_candidates, hunt_source_state, hunt_quota, hunt_cycles TO {role};"
_COLS = [f.name for f in fields(Candidate)]


class HuntStore(Protocol):
    async def init(self) -> None: ...
    async def get_by_domain(self, domain: str) -> Candidate | None: ...
    async def get_by_verdict(self, verdict_id: str) -> Candidate | None: ...
    async def upsert(self, c: Candidate) -> None: ...
    async def list(self, statuses: tuple[str, ...] | None = None, limit: int = 500) -> list[Candidate]: ...
    async def counts(self) -> dict[str, int]: ...
    async def source_state(self, source_id: str) -> dict[str, Any]: ...
    async def put_source_state(self, source_id: str, state: dict[str, Any]) -> None: ...
    async def quota_take(self, quota: str, window_start: datetime, limit: int) -> bool: ...
    async def quota_used(self, quota: str, window_start: datetime) -> int: ...
    async def cycle_put(self, cycle: dict[str, Any]) -> None: ...
    async def last_cycle(self) -> dict[str, Any] | None: ...
    async def try_lock(self) -> bool: ...
    async def unlock(self) -> None: ...


class MemoryHuntStore:
    def __init__(self) -> None:
        self.rows: dict[str, Candidate] = {}  # domain -> candidate
        self.states: dict[str, dict[str, Any]] = {}
        self.quota: dict[tuple[str, datetime], int] = {}
        self.cycles: list[dict[str, Any]] = []
        self._locked = False

    async def init(self) -> None:
        return None

    async def get_by_domain(self, domain: str) -> Candidate | None:
        return self.rows.get(domain)

    async def get_by_verdict(self, verdict_id: str) -> Candidate | None:
        return next((c for c in self.rows.values() if c.verdict_id == verdict_id), None)

    async def upsert(self, c: Candidate) -> None:
        old = self.rows.get(c.domain)
        if old is not None and old.candidate_id != c.candidate_id:
            c = replace(c, candidate_id=old.candidate_id)  # one row per domain; the first id stays
        self.rows[c.domain] = c

    async def list(self, statuses: tuple[str, ...] | None = None, limit: int = 500) -> list[Candidate]:
        out = [c for c in self.rows.values() if statuses is None or c.status in statuses]
        out.sort(key=lambda c: (-c.prescore, c.first_seen, c.candidate_id))
        return out[:limit]

    async def counts(self) -> dict[str, int]:
        return dict(Counter(c.status for c in self.rows.values()))

    async def source_state(self, source_id: str) -> dict[str, Any]:
        return dict(self.states.get(source_id, {}))

    async def put_source_state(self, source_id: str, state: dict[str, Any]) -> None:
        self.states[source_id] = dict(state)

    async def quota_take(self, quota: str, window_start: datetime, limit: int) -> bool:
        k = (quota, window_start)
        if self.quota.get(k, 0) >= limit:
            return False
        self.quota[k] = self.quota.get(k, 0) + 1
        return True

    async def quota_used(self, quota: str, window_start: datetime) -> int:
        return self.quota.get((quota, window_start), 0)

    async def cycle_put(self, cycle: dict[str, Any]) -> None:
        self.cycles = [c for c in self.cycles if c["cycle_id"] != cycle["cycle_id"]] + [dict(cycle)]

    async def last_cycle(self) -> dict[str, Any] | None:
        return dict(self.cycles[-1]) if self.cycles else None

    async def try_lock(self) -> bool:
        if self._locked:
            return False
        self._locked = True
        return True

    async def unlock(self) -> None:
        self._locked = False


def _row_to_candidate(r: dict[str, Any]) -> Candidate:
    kw = {k: r[k] for k in _COLS if k in r}
    kw["reasons"] = tuple(r.get("reasons") or ())
    kw["provenance"] = dict(r.get("provenance") or {})
    return Candidate(**kw)


class PgHuntStore:
    """Postgres store. DDL runs as the table owner (FL_DATABASE_OWNER_URL) when given, like falcon_sentinel/db.py."""

    def __init__(self, pool: Any, owner_dsn: str | None = None, app_role: str | None = None) -> None:
        self.pool = pool
        self.owner_dsn, self.app_role = owner_dsn, app_role
        self._lock_conn: Any = None
        self._mutex = asyncio.Lock()

    async def init(self) -> None:
        import psycopg

        from ..db import ROLE_RE

        ddl = MIGRATION.read_text(encoding="utf-8")
        if self.owner_dsn:
            async with await psycopg.AsyncConnection.connect(self.owner_dsn, autocommit=True) as c:
                await c.execute(ddl)
                if self.app_role:
                    if not ROLE_RE.match(self.app_role):
                        raise ValueError("bad FL_SENTINEL_DB_ROLE")
                    await c.execute(GRANTS.format(role=self.app_role))
        else:
            async with self.pool.connection() as c:
                await c.execute(ddl)

    async def _one(self, where: str, arg: Any) -> Candidate | None:
        async with self.pool.connection() as c:
            cur = await c.execute(f"SELECT {', '.join(_COLS)} FROM hunt_candidates WHERE {where}=%s", (arg,))  # noqa: S608 - fixed column names
            r = await cur.fetchone()
        return _row_to_candidate(dict(zip(_COLS, r, strict=True))) if r else None

    async def get_by_domain(self, domain: str) -> Candidate | None:
        return await self._one("domain", domain)

    async def get_by_verdict(self, verdict_id: str) -> Candidate | None:
        return await self._one("verdict_id", verdict_id)

    async def upsert(self, c: Candidate) -> None:
        from psycopg.types.json import Jsonb
        from sentinel_core.hunt.candidates import sha256_hex

        vals = {k: getattr(c, k) for k in _COLS}
        vals["reasons"] = Jsonb(sorted(set(c.reasons)))
        prov = dict(c.provenance)
        if isinstance(prov.get("retrieved_at"), datetime):
            prov["retrieved_at"] = prov["retrieved_at"].isoformat()
        vals["provenance"] = Jsonb(prov)
        cols = [*_COLS, "domain_sha256"]
        vals["domain_sha256"] = sha256_hex(c.domain)
        upd = ", ".join(f"{k}=EXCLUDED.{k}" for k in cols if k not in ("candidate_id", "domain", "first_seen"))
        sql = (
            f"INSERT INTO hunt_candidates ({', '.join(cols)}, updated_at) VALUES ({', '.join(['%s'] * len(cols))}, now())"  # noqa: S608
            f" ON CONFLICT (domain) DO UPDATE SET {upd}, updated_at=now()"
        )
        async with self.pool.connection() as conn:
            await conn.execute(sql, [vals[k] for k in cols])

    async def list(self, statuses: tuple[str, ...] | None = None, limit: int = 500) -> list[Candidate]:
        async with self.pool.connection() as c:
            cur = await c.execute(
                f"SELECT {', '.join(_COLS)} FROM hunt_candidates WHERE (%s::text[] IS NULL OR status = ANY(%s))"  # noqa: S608
                " ORDER BY prescore DESC, first_seen, candidate_id LIMIT %s",
                (list(statuses) if statuses else None, list(statuses) if statuses else None, limit),
            )
            rows = await cur.fetchall()
        return [_row_to_candidate(dict(zip(_COLS, r, strict=True))) for r in rows]

    async def counts(self) -> dict[str, int]:
        async with self.pool.connection() as c:
            cur = await c.execute("SELECT status, count(*) FROM hunt_candidates GROUP BY status")
            return {str(s): int(n) for s, n in await cur.fetchall()}

    async def source_state(self, source_id: str) -> dict[str, Any]:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT cursor, backoff_until, failures, last_success, last_error FROM hunt_source_state WHERE source_id=%s",
                (source_id,),
            )
            r = await cur.fetchone()
        if not r:
            return {}
        return {"cursor": r[0], "backoff_until": r[1], "failures": r[2], "last_success": r[3], "last_error": r[4]}

    async def put_source_state(self, source_id: str, state: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as c:
            await c.execute(
                "INSERT INTO hunt_source_state (source_id, cursor, backoff_until, failures, last_success, last_error, updated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (source_id) DO UPDATE SET cursor=EXCLUDED.cursor,"
                " backoff_until=EXCLUDED.backoff_until, failures=EXCLUDED.failures, last_success=EXCLUDED.last_success,"
                " last_error=EXCLUDED.last_error, updated_at=now()",
                (
                    source_id,
                    Jsonb(state.get("cursor") or {}),
                    state.get("backoff_until"),
                    int(state.get("failures") or 0),
                    state.get("last_success"),
                    state.get("last_error"),
                ),
            )

    async def quota_take(self, quota: str, window_start: datetime, limit: int) -> bool:
        async with self.pool.connection() as c:
            await c.execute(
                "INSERT INTO hunt_quota (quota, window_start, used) VALUES (%s,%s,0) ON CONFLICT DO NOTHING",
                (quota, window_start),
            )
            cur = await c.execute(
                "UPDATE hunt_quota SET used=used+1 WHERE quota=%s AND window_start=%s AND used < %s RETURNING used",
                (quota, window_start, limit),
            )
            return await cur.fetchone() is not None

    async def quota_used(self, quota: str, window_start: datetime) -> int:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT used FROM hunt_quota WHERE quota=%s AND window_start=%s", (quota, window_start)
            )
            r = await cur.fetchone()
        return int(r[0]) if r else 0

    async def cycle_put(self, cycle: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        async with self.pool.connection() as c:
            await c.execute(
                "INSERT INTO hunt_cycles (cycle_id, started_at, finished_at, outcome, stats) VALUES (%s,%s,%s,%s,%s)"
                " ON CONFLICT (cycle_id) DO UPDATE SET finished_at=EXCLUDED.finished_at, outcome=EXCLUDED.outcome,"
                " stats=EXCLUDED.stats",
                (
                    cycle["cycle_id"],
                    cycle["started_at"],
                    cycle.get("finished_at"),
                    cycle.get("outcome"),
                    Jsonb(json.loads(json.dumps(cycle.get("stats") or {}, default=str))),
                ),
            )

    async def last_cycle(self) -> dict[str, Any] | None:
        async with self.pool.connection() as c:
            cur = await c.execute(
                "SELECT cycle_id, started_at, finished_at, outcome, stats FROM hunt_cycles ORDER BY started_at DESC LIMIT 1"
            )
            r = await cur.fetchone()
        if not r:
            return None
        return {"cycle_id": r[0], "started_at": r[1], "finished_at": r[2], "outcome": r[3], "stats": r[4]}

    async def try_lock(self) -> bool:
        async with self._mutex:
            if self._lock_conn is not None:
                return False
            conn = await self.pool.getconn()
            cur = await conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
            r = await cur.fetchone()
            if r and r[0]:
                self._lock_conn = conn
                return True
            await self.pool.putconn(conn)
            return False

    async def unlock(self) -> None:
        async with self._mutex:
            if self._lock_conn is None:
                return
            conn, self._lock_conn = self._lock_conn, None
            try:
                await conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            finally:
                await self.pool.putconn(conn)
