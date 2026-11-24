"""Operator-selectable language-model route (``FL_LLM_ROUTE``) and its shared runtime switch.

Modes:
- ``cloud_with_local_fallback``: Anthropic first; on error, timeout or rate limit the local model answers.
- ``local``: sovereign. The local model only; people's text never leaves this machine.
- ``cloud_only``: Anthropic only, no local fallback.
- ``auto``: ``cloud_with_local_fallback`` when an API key is set, else ``local``.

``FL_SOVEREIGN_MODE=1`` always means ``local`` and cannot be overridden at runtime (a hard safety floor).
The runtime override lives in Redis (key ``fl:llm_route``) so the API, worker and sentinel all read the same
value; each router re-reads it at most every ``REFRESH_S`` seconds, with no restart. The route never touches a
score: the arbiter still sets it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

RouteMode = Literal["cloud_with_local_fallback", "local", "cloud_only", "auto"]
EffectiveMode = Literal["cloud_with_local_fallback", "local", "cloud_only"]
ROUTE_MODES: tuple[RouteMode, ...] = ("cloud_with_local_fallback", "local", "cloud_only", "auto")
# Local models actually served (README "Models we use"): Inkling via Ollama, Qwen 3.8 via the OpenAI-compatible gate.
LOCAL_MODELS: tuple[str, ...] = ("inkling-2-mini-chat", "qwen3.8:27b")
REDIS_KEY = "fl:llm_route"
REFRESH_S = 3.0
REDIS_TIMEOUT_S = 0.5


def parse_mode(value: str | None) -> RouteMode | None:
    v = (value or "").strip().lower()
    return next((m for m in ROUTE_MODES if m == v), None)


@dataclass(frozen=True, slots=True)
class RouteSetting:
    mode: RouteMode = "auto"
    local_model: str | None = None  # None = use FL_LOCAL_MODEL
    updated_at: str | None = None
    updated_by: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "mode": self.mode,
                "local_model": self.local_model,
                "updated_at": self.updated_at,
                "updated_by": self.updated_by,
            }
        )

    @classmethod
    def from_json(cls, raw: str | bytes | None) -> RouteSetting | None:
        if not raw:
            return None
        try:
            d = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(d, dict):
            return None
        mode = parse_mode(d.get("mode"))
        lm = d.get("local_model")
        if mode is None or (lm is not None and lm not in LOCAL_MODELS):
            return None  # an invalid stored value is ignored, never trusted
        ub = d.get("updated_by")
        ua = d.get("updated_at")
        return cls(mode, lm, ua if isinstance(ua, str) else None, ub if isinstance(ub, str) else None)


def effective_mode(mode: RouteMode, *, sovereign: bool, cloud_available: bool) -> tuple[EffectiveMode, str | None]:
    """Resolve a requested mode to what can actually run, with a reason when it was downgraded."""
    if sovereign:
        return "local", None if mode == "local" else "sovereign_mode"
    if mode == "auto":
        return ("cloud_with_local_fallback", None) if cloud_available else ("local", "no_api_key")
    if mode in ("cloud_with_local_fallback", "cloud_only") and not cloud_available:
        return ("local", "no_api_key") if mode == "cloud_with_local_fallback" else ("cloud_only", "no_api_key")
    return mode, None


class RedisLike(Protocol):
    def get(self, name: Any, /) -> Any: ...
    def set(self, name: Any, value: Any, /) -> Any: ...


async def read_setting(redis: RedisLike) -> RouteSetting | None:
    return RouteSetting.from_json(await redis.get(REDIS_KEY))


async def write_setting(redis: RedisLike, mode: RouteMode, local_model: str | None, by: str) -> RouteSetting:
    s = RouteSetting(mode, local_model, datetime.now(UTC).isoformat(timespec="seconds"), by)
    await redis.set(REDIS_KEY, s.to_json())
    return s


class RouteSource(Protocol):
    async def get(self) -> RouteSetting | None: ...


class RedisRouteSource:
    """Reads the shared setting, cached for ``ttl_s``. Redis trouble keeps the last known value."""

    def __init__(self, redis: RedisLike, ttl_s: float = REFRESH_S, clock: Any = time.monotonic) -> None:
        self._redis = redis
        self._ttl = ttl_s
        self._clock = clock
        self._at = -1e9
        self._value: RouteSetting | None = None

    async def get(self) -> RouteSetting | None:
        now = self._clock()
        if now - self._at < self._ttl:
            return self._value
        self._at = now
        with contextlib.suppress(Exception):  # never fail an LLM call because the switch store is down
            self._value = await asyncio.wait_for(read_setting(self._redis), REDIS_TIMEOUT_S)
        return self._value


def route_source_from_env(env: Any = None) -> RouteSource | None:
    """A Redis-backed source when ``REDIS_URL`` is set (worker, sentinel), else None (env only)."""
    import os

    url = (os.environ if env is None else env).get("REDIS_URL")
    if not url:
        return None
    import redis.asyncio as aioredis

    return RedisRouteSource(aioredis.from_url(url, decode_responses=True))
