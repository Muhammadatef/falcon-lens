"""Final-verdict store: Postgres ``verdicts`` (doc jsonb) + ``evidence`` rows; memory for tests."""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any, Protocol

log = logging.getLogger("falcon.worker.store")

MIGRATIONS = ("001_verdicts_evidence.sql",)


class StoreError(Exception):
    pass


class VerdictStore(Protocol):
    async def migrate(self) -> None: ...
    async def upsert(self, doc: dict[str, Any]) -> None: ...
    async def get(self, verdict_id: str) -> dict[str, Any] | None: ...
    async def close(self) -> None: ...


def migration_sql() -> list[str]:
    pkg = resources.files("falcon_worker") / "migrations"
    return [(pkg / name).read_text(encoding="utf-8") for name in MIGRATIONS]


def evidence_rows(doc: dict[str, Any]) -> list[tuple[Any, ...]]:
    rows = []
    for e in doc.get("evidence", []):
        rows.append(
            (
                doc["verdict_id"],
                e["id"],
                e["signal"],
                e["family"],
                e["tier"],
                float(e.get("weight", 0.0)),
                e.get("polarity", "neutral"),
                e.get("hard_rule"),
                e["source"],
                float(e.get("confidence", 1.0)),
                e.get("error"),
                json.dumps(e.get("observed"), ensure_ascii=False),
                e.get("latency_ms"),
            )
        )
    return rows


class MemoryStore:
    def __init__(self) -> None:
        self.verdicts: dict[str, dict[str, Any]] = {}
        self.evidence: dict[tuple[str, str], tuple[Any, ...]] = {}

    async def migrate(self) -> None:
        return None

    async def upsert(self, doc: dict[str, Any]) -> None:
        self.verdicts[doc["verdict_id"]] = json.loads(json.dumps(doc))
        for row in evidence_rows(doc):
            self.evidence[(row[0], row[1])] = row

    async def get(self, verdict_id: str) -> dict[str, Any] | None:
        return self.verdicts.get(verdict_id)

    async def close(self) -> None:
        return None


class PgStore:
    """asyncpg pool, created lazily so the worker starts (and degrades) without Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # type: ignore[import-untyped]

            try:
                self._pool = await asyncpg.create_pool(self._dsn, min_size=0, max_size=5, timeout=5, command_timeout=5)
            except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
                raise StoreError(type(exc).__name__) from exc
        return self._pool

    async def migrate(self) -> None:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            for sql in migration_sql():
                await conn.execute(sql)

    async def upsert(self, doc: dict[str, Any]) -> None:
        pool = await self._get_pool()
        body = json.dumps(doc, ensure_ascii=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO verdicts (verdict_id, doc, created_at) VALUES ($1, $2::jsonb, now()) "
                "ON CONFLICT (verdict_id) DO UPDATE SET doc = EXCLUDED.doc",
                doc["verdict_id"],
                body,
            )
            await conn.execute("DELETE FROM evidence WHERE verdict_id = $1", doc["verdict_id"])
            rows = evidence_rows(doc)
            if rows:
                await conn.executemany(
                    "INSERT INTO evidence (verdict_id, evidence_id, signal, family, tier, weight,"
                    " polarity, hard_rule, source, confidence, error, observed, latency_ms)"
                    " VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13)",
                    rows,
                )

    async def get(self, verdict_id: str) -> dict[str, Any] | None:
        pool = await self._get_pool()
        row = await pool.fetchrow("SELECT doc FROM verdicts WHERE verdict_id = $1", verdict_id)
        if row is None:
            return None
        raw = row["doc"]
        parsed = json.loads(raw) if isinstance(raw, str | bytes) else raw
        return parsed if isinstance(parsed, dict) else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
