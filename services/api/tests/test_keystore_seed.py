"""Regression: a configured key already stored under another key_id must not take the key store down (P0 2026-11-24)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, KeyRecord, MemoryKeyStore, StoreUnavailableError, fingerprint, hash_key
from tests.conftest import OPERATOR_KEY, SANDBOX_KEY, FakeStore, make_settings

PEPPER = "test-pepper"  # matches make_settings
HUNT_KEY = "test-hunt-key"  # placeholder, not a credential
URL = "http://falcon-demo-bank-secure.test/"


def _row(key_id: str, key: str, scopes: list[str], revoked: bool = False) -> KeyRecord:
    return KeyRecord(
        key_id,
        fingerprint(PEPPER, key),
        hash_key(PEPPER, key),
        scopes,
        60,
        key_id,
        revoked_at=datetime.now(UTC) if revoked else None,
    )


def _client(ks: MemoryKeyStore, redis: Any, store: FakeStore) -> httpx.AsyncClient:
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store, keystore=ks)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_env_key_already_created_by_script_does_not_break_auth(
    redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    ks = MemoryKeyStore()
    await ks.put(_row("key_87b0544cfcd2", HUNT_KEY, ["hunt"]))  # what scripts/create_api_key.py left behind
    monkeypatch.setenv("FL_HUNT_API_KEY", HUNT_KEY)
    async with _client(ks, redis, store) as c:
        r = await c.get("/v1/verdicts", headers={"X-API-Key": OPERATOR_KEY})
        assert r.status_code == 200, r.text
        ok = await c.post("/v1/check/url", json={"url": URL, "channel": "hunt"}, headers={"X-API-Key": HUNT_KEY})
        assert ok.status_code == 202, ok.text
    assert "sentinel-hunt" not in ks.rows
    assert ks.rows["key_87b0544cfcd2"].scopes == ["hunt"]


async def test_revoked_stored_row_stays_revoked(redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    ks = MemoryKeyStore()
    await ks.put(_row("key_old", HUNT_KEY, ["hunt"], revoked=True))
    monkeypatch.setenv("FL_HUNT_API_KEY", HUNT_KEY)
    async with _client(ks, redis, store) as c:
        bad = await c.post("/v1/check/url", json={"url": URL, "channel": "hunt"}, headers={"X-API-Key": HUNT_KEY})
        assert bad.status_code == 401
        assert (await c.get("/v1/verdicts", headers={"X-API-Key": OPERATOR_KEY})).status_code == 200


async def test_failing_seed_is_skipped_not_fatal(redis: Any, store: FakeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    class FlakyStore(MemoryKeyStore):
        async def put(self, rec: KeyRecord) -> None:
            if rec.key_id == "sentinel-hunt":
                raise StoreUnavailableError("UniqueViolationError")
            await super().put(rec)

    monkeypatch.setenv("FL_HUNT_API_KEY", HUNT_KEY)
    async with _client(FlakyStore(), redis, store) as c:
        assert (await c.get("/v1/verdicts", headers={"X-API-Key": OPERATOR_KEY})).status_code == 200
        r = await c.post("/v1/check/url", json={"url": URL}, headers={"X-API-Key": SANDBOX_KEY})
        assert r.status_code in (200, 202)
        assert (await c.get("/v1/verdicts", headers={"X-API-Key": HUNT_KEY})).status_code == 401


async def test_unknown_scope_dropped_known_scopes_kept() -> None:
    ks = MemoryKeyStore()
    await ks.put(_row("key_mixed", "k-mixed", ["read", "future-scope"]))
    await ks.put(_row("key_unknown", "k-unknown", ["future-scope"]))
    auth = Authenticator(ks, PEPPER)
    p = await auth.authenticate("k-mixed")
    assert p is not None
    assert p.scopes == frozenset({"read"})
    assert await auth.authenticate("k-unknown") is None  # fail closed for that key only


async def test_memory_store_enforces_unique_fingerprint() -> None:
    ks = MemoryKeyStore()
    await ks.put(_row("a", "same", ["read"]))
    with pytest.raises(StoreUnavailableError):
        await ks.put(_row("b", "same", ["read"]))
