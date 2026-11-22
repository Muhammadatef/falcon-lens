"""Worker wiring: /metrics exposes the fl_ names smoke reads; optional live Postgres round-trip."""

from __future__ import annotations

import os
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from falcon_core.cascade import new_verdict_id
from falcon_core.security import BlockReason
from falcon_core.service import create_app
from falcon_worker.main import build_worker, guard_policy
from falcon_worker.store import PgStore


def test_metrics_expose_checks_and_ssrf_counters() -> None:
    app = create_app("worker-test")
    r: Any = fakeredis.FakeAsyncRedis(decode_responses=True)
    worker, _store, _sandbox = build_worker(app, r)
    worker.metrics.on_ssrf_block(BlockReason.METADATA)
    text = TestClient(app).get("/metrics").text
    assert "fl_checks_total" in text
    assert 'fl_ssrf_blocked_total{reason="metadata"}' in text
    assert "fl_stage_latency_seconds" in text
    assert "fl_stage_latency_seconds" not in generate_latest(app.state.registry).decode()  # no dupes


def test_guard_policy_allow_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", "fixtures, falcon-demo-bank.test")
    assert guard_policy().allow_hosts == frozenset({"fixtures", "falcon-demo-bank.test"})
    monkeypatch.delenv("FL_SSRF_ALLOW_HOSTS")
    assert guard_policy().allow_hosts == frozenset()


@pytest.mark.skipif(not os.environ.get("FL_TEST_DATABASE_URL"), reason="no FL_TEST_DATABASE_URL")
async def test_pg_store_roundtrip() -> None:
    store = PgStore(os.environ["FL_TEST_DATABASE_URL"])
    await store.migrate()
    await store.migrate()  # idempotent
    vid = new_verdict_id()
    doc: dict[str, Any] = {
        "verdict_id": vid,
        "final": True,
        "evidence": [
            {"id": "ev_0123456789abcdef", "signal": "page.cred_form", "family": "page",
             "tier": "T2", "weight": 1.5, "polarity": "risk", "hard_rule": "H1",
             "source": "sandbox", "confidence": 1.0, "error": None, "observed": {"present": True}}
        ],
    }  # fmt: skip
    await store.upsert(doc)
    await store.upsert(doc)
    assert await store.get(vid) == doc
    await store.close()
