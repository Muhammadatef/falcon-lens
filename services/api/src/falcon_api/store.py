"""Read-side access to final verdicts in Postgres (table `verdicts`, jsonb column `doc`)."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

log = logging.getLogger("falcon.api.store")


class StoreUnavailableError(Exception):
    pass


class VerdictStore(Protocol):
    async def get(self, verdict_id: str) -> dict[str, Any] | None: ...
    async def close(self) -> None: ...


class PgVerdictStore:
    """asyncpg-backed store; the pool is created lazily so the API starts without Postgres."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _get_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # type: ignore[import-untyped]

            try:
                self._pool = await asyncpg.create_pool(
                    self._dsn, min_size=0, max_size=5, timeout=3, command_timeout=3
                )
            except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
                raise StoreUnavailableError(type(exc).__name__) from exc
        return self._pool

    async def get(self, verdict_id: str) -> dict[str, Any] | None:
        import asyncpg

        pool = await self._get_pool()
        try:
            row = await pool.fetchrow("SELECT doc FROM verdicts WHERE verdict_id = $1", verdict_id)
        except asyncpg.UndefinedTableError:
            return None  # worker has not created the table yet
        except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
            raise StoreUnavailableError(type(exc).__name__) from exc
        if row is None:
            return None
        doc = row["doc"]
        parsed = json.loads(doc) if isinstance(doc, str | bytes) else doc
        return parsed if isinstance(parsed, dict) else None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
