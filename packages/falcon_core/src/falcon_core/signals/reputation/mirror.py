"""Private OpenPhish mirror: load, look up, refresh job, ``feed.updated`` event.

Licence: OpenPhish terms bar redistribution (DECISIONS.md). The mirror lives only in Redis (set ``feed:openphish``)
and is built from ``data/private/feeds/openphish/2*.jsonl`` (gitignored). Members are hashes, never URLs:
bare sha256 hex digests: the canonical URL hash and the lowercase ASCII host hash (host entries only for bare-path listings, so a phishing page on a
shared host never condemns the whole host). Nothing here logs or emits a full URL.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from falcon_core.signals.cache import KV
from falcon_core.signals.reputation import metrics
from falcon_core.signals.url.canonical import canonicalize

log = logging.getLogger(__name__)

FEED = "openphish"
SET_KEY = f"feed:{FEED}"
UPDATED_KEY = f"feed:{FEED}:updated_at"
FRESH_MAX_AGE_S = 6 * 3600  # SCORING H2
DEFAULT_FEED_DIR = Path("data/private/feeds/openphish")
DEFAULT_MAX_ROW_AGE_DAYS = 14
_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def simple_canon(url: str) -> str | None:
    """Same canonical form the collector (evals/collect/openphish.py) hashes: lower host, no fragment/default port."""
    try:
        p = urlsplit(url.strip())
        host, port = p.hostname, p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not host:
        return None
    netloc = host.lower() + (f":{port}" if port and port not in (80, 443) else "")
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


def lookup_keys(url: str) -> tuple[list[str], str | None]:
    """(exact-url keys, host key) for a URL. Two canonical forms so collector and signal canonicalisers agree."""
    keys: list[str] = []
    sc = simple_canon(url)
    if sc:
        keys.append(_sha(sc))
    c = canonicalize(url)
    host: str | None = None
    if c.ok and not c.is_data_uri and c.host_ascii:
        host = _sha(c.host_ascii)
        full = c.url.split("#", 1)[0]
        k = _sha(full)
        if k not in keys:
            keys.append(k)
    return keys, host


def row_members(url: str, sha256: str | None = None) -> list[str]:
    """Set members for one feed row."""
    out: list[str] = []
    keys, _ = lookup_keys(url)
    out.extend(keys)
    if sha256 and sha256 not in out:
        out.append(sha256)
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return out
    c = canonicalize(url)
    if c.ok and c.host_ascii and p.path in ("", "/") and not p.query:
        out.append(_sha(c.host_ascii))
    return out


@dataclass(frozen=True)
class MirrorHit:
    match: str | None  # "url" | "host" | None
    updated_at: float | None  # epoch seconds, None if the mirror was never loaded


class FeedMirror:
    """ctx.mirror implementation over a ``KV`` (Redis or in-memory)."""

    def __init__(self, kv: KV) -> None:
        self._kv = kv

    async def updated_at(self, feed: str = FEED) -> float | None:
        v = await self._kv.get(f"feed:{feed}:updated_at")
        return float(v) if isinstance(v, int | float) else None

    async def lookup(self, url: str, feed: str = FEED) -> MirrorHit:
        upd = await self.updated_at(feed)
        if upd is None:
            return MirrorHit(None, None)
        keys, host = lookup_keys(url)
        for k in keys:
            if await self._kv.sismember(f"feed:{feed}", k):
                return MirrorHit("url", upd)
        if host and await self._kv.sismember(f"feed:{feed}", host):
            return MirrorHit("host", upd)
        return MirrorHit(None, upd)

    async def load(self, members: list[str], updated_at: float, feed: str = FEED) -> int:
        n = await self._kv.replace_set(f"feed:{feed}", members)
        await self._kv.set(f"feed:{feed}:updated_at", updated_at)
        return n


def feed_enabled_openphish() -> bool:
    return os.environ.get("FL_FEED_OPENPHISH_ENABLED", "true").strip().lower() not in (
        "0",
        "false",
        "no",
        "",
    )


# ----------------------------------------------------------------- refresh job


def _read_rows(feed_dir: Path, now: float, max_age_days: int) -> tuple[list[str], int]:
    members: set[str] = set()
    rows = 0
    cutoff = now - max_age_days * 86400
    for f in sorted(
        feed_dir.glob("2*.jsonl")
    ):  # the collector's dated files; excludes snapshot_queue.jsonl
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    url = r["url"]
                except (ValueError, KeyError, TypeError):
                    continue
                fs = r.get("first_seen")
                if isinstance(fs, str):
                    try:
                        if datetime.fromisoformat(fs.replace("Z", "+00:00")).timestamp() < cutoff:
                            continue
                    except ValueError:
                        pass
                if not isinstance(url, str):
                    continue
                rows += 1
                members.update(
                    row_members(url, r.get("sha256") if isinstance(r.get("sha256"), str) else None)
                )
    return sorted(members), rows


def _feed_updated_at(feed_dir: Path) -> float | None:
    """Last poll time: state.json ``last_poll_utc`` (written by the collector), else newest file mtime."""
    st = feed_dir / "state.json"
    try:
        return datetime.fromisoformat(
            json.loads(st.read_text())["last_poll_utc"].replace("Z", "+00:00")
        ).timestamp()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    mt = [p.stat().st_mtime for p in feed_dir.glob("2*.jsonl")]
    return max(mt) if mt else None


def new_event_id(now_ms: int | None = None) -> str:
    """``evt_`` + 26-char Crockford ULID (event.schema.json)."""
    ms = int(time.time() * 1000) if now_ms is None else now_ms
    n = (ms << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_B32[n & 31])
        n >>= 5
    return "evt_" + "".join(reversed(chars))


def feed_updated_event(feed: str, entries: int, age_s: int, now: float) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "event_id": new_event_id(int(now * 1000)),
        "type": "feed.updated",
        "occurred_at": datetime.fromtimestamp(now, tz=UTC).isoformat().replace("+00:00", "Z"),
        "source": "live",
        "verdict_id": None,
        "payload": {"feed": feed, "entries": entries, "age_s": age_s},
    }


Publisher = Callable[[dict[str, Any]], Awaitable[None]]


def redis_publisher(client: Any, stream: str = "fl:events") -> Publisher:
    """XADD the event JSON under field ``event`` (field layout is a DECISIONS assumption)."""

    async def publish(ev: dict[str, Any]) -> None:
        await client.xadd(
            stream,
            {"event": json.dumps(ev, separators=(",", ":"))},
            maxlen=100_000,
            approximate=True,
        )

    return publish


@dataclass(frozen=True)
class RefreshResult:
    entries: int
    rows: int
    updated_at: float | None
    age_s: int | None
    loaded: bool


async def refresh_openphish(
    kv: KV,
    feed_dir: Path | None = None,
    *,
    now: float | None = None,
    publish: Publisher | None = None,
    max_row_age_days: int = DEFAULT_MAX_ROW_AGE_DAYS,
) -> RefreshResult:
    """Load the private OpenPhish rows into the mirror, set metrics, emit ``feed.updated``."""
    t = time.time() if now is None else now
    metrics.set_enabled(FEED, feed_enabled_openphish())
    d = feed_dir or Path(os.environ.get("FL_OPENPHISH_FEED_DIR", str(DEFAULT_FEED_DIR)))
    if not feed_enabled_openphish() or not d.is_dir():
        return RefreshResult(0, 0, None, None, False)
    members, rows = await asyncio.to_thread(_read_rows, d, t, max_row_age_days)
    upd = _feed_updated_at(d)
    if upd is None:
        return RefreshResult(0, 0, None, None, False)
    n = await FeedMirror(kv).load(members, upd)
    age = int(max(0, t - upd))
    metrics.set_age(FEED, age)
    if publish is not None:
        try:
            await publish(feed_updated_event(FEED, n, age, t))
        except Exception:  # noqa: BLE001 - bus outage must not break the mirror
            log.warning("feed.updated publish failed", exc_info=True)
    log.info("openphish mirror refreshed", extra={"entries": n, "rows": rows, "age_s": age})
    return RefreshResult(n, rows, upd, age, True)


async def run_refresh_loop(
    kv: KV,
    feed_dir: Path | None = None,
    *,
    interval_s: float = 900.0,
    publish: Publisher | None = None,
) -> None:
    """Periodic job (worker lifespan task). Re-reads local files; makes no network call."""
    last: tuple[int, float | None] | None = None
    while True:
        try:
            res = await refresh_openphish(kv, feed_dir, publish=None)
            state = (res.entries, res.updated_at)
            if res.loaded and publish is not None and state != last:
                await publish(feed_updated_event(FEED, res.entries, res.age_s or 0, time.time()))
            last = state
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.warning("openphish refresh failed", exc_info=True)
        await asyncio.sleep(interval_s)
