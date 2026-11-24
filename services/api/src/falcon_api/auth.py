"""API keys: argon2id hashed at rest (peppered), scopes, per-key rate limits.

Keys are opaque strings. Lookup uses a pepper-keyed HMAC fingerprint (an index, not a secret); the key is then
verified against its argon2id hash. Verified keys are cached in-process for a short TTL so argon2 cost is paid once.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

log = logging.getLogger("falcon.api.auth")

SCOPES = ("check", "read", "operator", "intel", "hunt")  # hunt: the Sentinel hunt mode, POST /v1/check/url only
CACHE_TTL_S = 30.0
NEG_CACHE_TTL_S = 5.0
CACHE_MAX = 2048
_HASHER = PasswordHasher()  # argon2id (RFC 9106 low-memory profile)


class StoreUnavailableError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    key_id: str
    scopes: frozenset[str]
    rate_limit_per_min: int
    label: str = ""


@dataclass
class KeyRecord:
    key_id: str
    fingerprint: str
    key_hash: str
    scopes: list[str]
    rate_limit_per_min: int
    label: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None


def fingerprint(pepper: str, key: str) -> str:
    return hmac.new(pepper.encode(), b"fp\0" + key.encode(), hashlib.sha256).hexdigest()


def _pre(pepper: str, key: str) -> str:
    return hmac.new(pepper.encode(), b"pw\0" + key.encode(), hashlib.sha256).hexdigest()


def hash_key(pepper: str, key: str) -> str:
    return _HASHER.hash(_pre(pepper, key))


def verify_key(pepper: str, key: str, key_hash: str) -> bool:
    try:
        return _HASHER.verify(key_hash, _pre(pepper, key))
    except (VerificationError, InvalidHashError):
        return False


def new_key() -> str:
    return "fl_" + secrets.token_urlsafe(32)


def ip_digest(pepper: str, ip: str) -> str:
    return hmac.new(pepper.encode(), b"ip\0" + ip.encode(), hashlib.sha256).hexdigest()[:20]


class KeyStore(Protocol):
    async def init(self) -> None: ...
    async def find(self, fp: str) -> KeyRecord | None: ...
    async def put(self, rec: KeyRecord) -> None: ...
    async def revoke(self, key_id: str) -> None: ...
    async def close(self) -> None: ...


class AuditLog(Protocol):
    async def append(self, entry: dict[str, Any]) -> None: ...


class MemoryKeyStore:
    def __init__(self) -> None:
        self.rows: dict[str, KeyRecord] = {}

    async def init(self) -> None:
        return None

    async def find(self, fp: str) -> KeyRecord | None:
        for r in self.rows.values():
            if r.fingerprint == fp:
                return r
        return None

    async def put(self, rec: KeyRecord) -> None:
        # Mirror the Postgres UNIQUE(fingerprint) constraint so tests see the same failure mode.
        if any(r.fingerprint == rec.fingerprint and k != rec.key_id for k, r in self.rows.items()):
            raise StoreUnavailableError("UniqueViolationError")
        self.rows[rec.key_id] = rec

    async def revoke(self, key_id: str) -> None:
        if key_id in self.rows:
            self.rows[key_id].revoked_at = datetime.now(UTC)

    async def close(self) -> None:
        return None


class MemoryAuditLog:
    """Append-only by construction: exposes `append` and a read-only view."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    async def append(self, entry: dict[str, Any]) -> None:
        self._rows.append(dict(entry))

    @property
    def rows(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._rows)


class Authenticator:
    def __init__(self, store: KeyStore, pepper: str) -> None:
        self.store = store
        self.pepper = pepper
        self._cache: OrderedDict[str, tuple[float, Principal | None]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def authenticate(self, key: str) -> Principal | None:
        fp = fingerprint(self.pepper, key)
        hit = self._cache.get(fp)
        now = time.monotonic()
        if hit and now - hit[0] < (CACHE_TTL_S if hit[1] else NEG_CACHE_TTL_S):
            self._cache.move_to_end(fp)
            return hit[1]
        rec = await self.store.find(fp)
        principal: Principal | None = None
        if rec is not None and rec.revoked_at is None:
            async with self._lock:  # argon2 is CPU/memory-bound: serialise to bound memory use
                ok = await asyncio.to_thread(verify_key, self.pepper, key, rec.key_hash)
            if ok:
                principal = self._principal(rec)
        self._cache[fp] = (now, principal)
        self._cache.move_to_end(fp)
        while len(self._cache) > CACHE_MAX:  # LRU: random bad keys cannot grow memory or evict everything at once
            self._cache.popitem(last=False)
        return principal

    @staticmethod
    def _principal(rec: KeyRecord) -> Principal | None:
        """Known scopes only: an unknown stored scope is dropped (fail closed for that scope, never the store)."""
        known = frozenset(s for s in rec.scopes if s in SCOPES)
        unknown = sorted(set(rec.scopes) - known)
        if unknown:
            log.warning("api key %s has unknown scopes %s; ignored", rec.key_id, unknown)
        if not known:
            return None
        return Principal(rec.key_id, known, rec.rate_limit_per_min, rec.label)

    async def seed(self, key_id: str, key: str, scopes: list[str], rate: int, label: str) -> None:
        """Idempotently register a configured key (hash recomputed only when something changed).

        If the same key value is already stored under another key_id (e.g. created with scripts/create_api_key.py
        and then copied into .env), the stored row wins: inserting it again would violate UNIQUE(fingerprint) and
        take the whole key store down. A revoked stored row stays revoked (fail closed).
        """
        fp = fingerprint(self.pepper, key)
        existing = await self.store.find(fp)
        if existing is not None and existing.key_id != key_id:
            log.warning(
                "configured key %s is already stored as %s (revoked=%s, scopes=%s); keeping the stored row",
                key_id,
                existing.key_id,
                existing.revoked_at is not None,
                sorted(existing.scopes),
            )
            return
        if (
            existing is not None
            and existing.key_id == key_id
            and existing.revoked_at is None
            and existing.scopes == scopes
            and existing.rate_limit_per_min == rate
        ):
            return
        h = await asyncio.to_thread(hash_key, self.pepper, key)
        await self.store.put(KeyRecord(key_id, fp, h, scopes, rate, label))

    async def create(self, label: str, scopes: list[str], rate: int) -> tuple[str, str]:
        bad = [s for s in scopes if s not in SCOPES]
        if bad or not scopes:
            raise ValueError(f"scopes must be a non-empty subset of {SCOPES}")
        key = new_key()
        key_id = "key_" + secrets.token_hex(6)
        h = await asyncio.to_thread(hash_key, self.pepper, key)
        await self.store.put(KeyRecord(key_id, fingerprint(self.pepper, key), h, scopes, rate, label))
        return key_id, key


DEFAULT_PREFIX = "change-me"


def refuse_default_secrets(env: str, secrets_in_use: dict[str, str | None]) -> None:
    """Outside FL_ENV=local, refuse to start while any secret still carries a `change-me*` placeholder."""
    if env == "local":
        return
    bad = sorted(k for k, v in secrets_in_use.items() if v and v.lower().startswith(DEFAULT_PREFIX))
    if bad:
        raise RuntimeError(f"refusing to start with FL_ENV={env}: placeholder values still set for {', '.join(bad)}")
