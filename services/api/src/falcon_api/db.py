"""Postgres-backed key store, audit log and citizen submissions (lazy pool, idempotent DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from falcon_api.auth import KeyConflictError, KeyRecord, StoreUnavailableError

DDL = """
CREATE TABLE IF NOT EXISTS api_keys (
  key_id text PRIMARY KEY,
  fingerprint text NOT NULL UNIQUE,
  key_hash text NOT NULL,
  scopes text[] NOT NULL,
  rate_limit_per_min int NOT NULL,
  label text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz
);
CREATE TABLE IF NOT EXISTS api_audit_log (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  key_id text,
  method text NOT NULL,
  path text NOT NULL,
  status int NOT NULL,
  request_id text,
  ip_digest text,
  note text
);
CREATE OR REPLACE FUNCTION fl_api_audit_immutable() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'api_audit_log is append-only'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS api_audit_immutable ON api_audit_log;
CREATE TRIGGER api_audit_immutable BEFORE UPDATE OR DELETE ON api_audit_log
  FOR EACH ROW EXECUTE FUNCTION fl_api_audit_immutable();
DROP TRIGGER IF EXISTS api_audit_no_truncate ON api_audit_log;
CREATE TRIGGER api_audit_no_truncate BEFORE TRUNCATE ON api_audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION fl_api_audit_immutable();
REVOKE UPDATE, DELETE, TRUNCATE ON api_audit_log FROM PUBLIC;
CREATE TABLE IF NOT EXISTS submissions (
  submission_id text PRIMARY KEY,
  kind text NOT NULL,
  input_kind text,
  verdict_id text,
  content_sha256 text,
  rating text,
  opt_in_text text,
  source text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""


class SubmissionStore(Protocol):
    async def add(self, row: dict[str, Any]) -> None: ...


class MemorySubmissionStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def add(self, row: dict[str, Any]) -> None:
        self.rows.append(dict(row))


class Db:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # type: ignore[import-untyped]

            try:
                self._pool = await asyncpg.create_pool(self._dsn, min_size=0, max_size=5, timeout=3, command_timeout=3)
            except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
                raise StoreUnavailableError(type(exc).__name__) from exc
        return self._pool

    async def run(self, sql: str, *args: Any) -> Any:
        import asyncpg

        pool = await self.pool()
        try:
            return await pool.fetch(sql, *args)
        except asyncpg.UniqueViolationError as exc:
            raise KeyConflictError(type(exc).__name__) from exc
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            raise StoreUnavailableError(type(exc).__name__) from exc

    async def init(self) -> None:
        import asyncpg

        pool = await self.pool()
        try:
            async with pool.acquire() as c:
                await c.execute("SELECT pg_advisory_lock(727001)")
                try:
                    await c.execute(DDL)
                finally:
                    await c.execute("SELECT pg_advisory_unlock(727001)")
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            raise StoreUnavailableError(type(exc).__name__) from exc

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()


class PgKeyStore:
    def __init__(self, db: Db) -> None:
        self.db = db

    async def init(self) -> None:
        await self.db.init()

    async def find(self, fp: str) -> KeyRecord | None:
        rows = await self.db.run(
            "SELECT key_id, fingerprint, key_hash, scopes, rate_limit_per_min, label, created_at, revoked_at "
            "FROM api_keys WHERE fingerprint = $1",
            fp,
        )
        if not rows:
            return None
        r = rows[0]
        return KeyRecord(
            r["key_id"],
            r["fingerprint"],
            r["key_hash"],
            list(r["scopes"]),
            r["rate_limit_per_min"],
            r["label"],
            r["created_at"],
            r["revoked_at"],
        )

    async def put(self, rec: KeyRecord) -> None:
        await self.db.run(
            "INSERT INTO api_keys (key_id, fingerprint, key_hash, scopes, rate_limit_per_min, label) "
            "VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (key_id) DO UPDATE SET fingerprint=EXCLUDED.fingerprint, "
            "key_hash=EXCLUDED.key_hash, scopes=EXCLUDED.scopes, rate_limit_per_min=EXCLUDED.rate_limit_per_min, "
            "label=EXCLUDED.label",  # revoked_at is kept: seeding or re-keying never un-revokes a key
            rec.key_id,
            rec.fingerprint,
            rec.key_hash,
            rec.scopes,
            rec.rate_limit_per_min,
            rec.label,
        )

    async def revoke(self, key_id: str) -> None:
        await self.db.run("UPDATE api_keys SET revoked_at = now() WHERE key_id = $1", key_id)

    async def close(self) -> None:
        await self.db.close()


class PgAuditLog:
    def __init__(self, db: Db) -> None:
        self.db = db

    async def append(self, e: dict[str, Any]) -> None:
        await self.db.run(
            "INSERT INTO api_audit_log (at, key_id, method, path, status, request_id, ip_digest, note) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            e["at"],
            e.get("key_id"),
            e["method"],
            e["path"],
            e["status"],
            e.get("request_id"),
            e.get("ip_digest"),
            e.get("note"),
        )


class PgSubmissionStore:
    def __init__(self, db: Db) -> None:
        self.db = db

    async def add(self, r: dict[str, Any]) -> None:
        at: datetime = r["created_at"]
        await self.db.run(
            "INSERT INTO submissions (submission_id, kind, input_kind, verdict_id, content_sha256, rating, "
            "opt_in_text, source, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            r["submission_id"],
            r["kind"],
            r.get("input_kind"),
            r.get("verdict_id"),
            r.get("content_sha256"),
            r.get("rating"),
            r.get("opt_in_text"),
            r["source"],
            at,
        )
