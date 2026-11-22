"""Test doubles for ``ctx.http`` (no network) and a minimal signal context."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from falcon_core.security.http import FetchFailed, FetchFailReason, FetchResult
from falcon_core.signals.base import Evidence
from falcon_core.signals.cache import MemoryCache

NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=UTC).timestamp()
FIX = Path(__file__).parent / "fixtures"
_EVIDENCE_SCHEMA = json.loads(
    (Path(__file__).parents[4] / "contracts" / "evidence.schema.json").read_text()
)


def fixture(name: str) -> str:
    return (FIX / name).read_text()


def result(body: bytes | str | Any, status: int = 200) -> FetchResult:
    if not isinstance(body, bytes | str):
        body = json.dumps(body)
    raw = body.encode() if isinstance(body, str) else body
    return FetchResult(
        status=status,
        final_url="https://x.test/",
        redirect_chain=(),
        headers={},
        body=raw,
        resolved_ip="203.0.113.7",
    )


def validate(evs: list[Evidence]) -> None:
    for e in evs:
        jsonschema.validate(e.to_dict(), _EVIDENCE_SCHEMA)


class FakeHTTP:
    """Routes by URL prefix. Values: FetchResult, Exception instance, or ('sleep', seconds)."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def _route(self, url: str) -> Any:
        for prefix, val in self.routes.items():
            if url.startswith(prefix):
                return val
        raise AssertionError(f"unrouted url {url}")

    async def fetch(
        self, url: str, *, timeout: float = 6.0, max_bytes: int = 0, **_: Any
    ) -> FetchResult:
        self.calls.append(url)
        val = self._route(url)
        if isinstance(val, tuple) and val[0] == "sleep":
            await asyncio.sleep(val[1])
            raise FetchFailed(FetchFailReason.TIMEOUT)
        if isinstance(val, Exception):
            raise val
        return val  # type: ignore[no-any-return]

    async def post(self, url: str, *, timeout: float = 6.0, **kw: Any) -> FetchResult:
        self.posts.append((url, kw))
        val = self._route(url)
        if isinstance(val, Exception):
            raise val
        return val  # type: ignore[no-any-return]


def _now() -> float:
    return NOW


@dataclass
class Ctx:
    url: str | None = None
    text: str | None = None
    input_type: str = "url"
    http: Any = None
    cache: Any = field(default_factory=MemoryCache)
    mirror: Any = None
    clock: Callable[[], float] = _now
    brands: Any = None
