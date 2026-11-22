from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from falcon_core.config import Settings
from falcon_core.logging import JsonFormatter, verdict_id_var
from falcon_core.service import create_app


def test_health_ready_metrics() -> None:
    async def bad() -> bool:
        return False

    client = TestClient(create_app("unit"))
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").status_code == 200
    assert "fl_service_info" in client.get("/metrics").text

    client = TestClient(create_app("unit", deps={"broken": bad}))
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["deps"] == {"broken": False}


def test_json_log_carries_verdict_id() -> None:
    record = logging.LogRecord("t", logging.INFO, "f", 1, "hello", (), None)
    token = verdict_id_var.set("vd_01JC8Z9Q3M5N7P2R4T6V8W0XYZ")
    try:
        out = json.loads(JsonFormatter("unit").format(record))
    finally:
        verdict_id_var.reset(token)
    assert out["verdict_id"] == "vd_01JC8Z9Q3M5N7P2R4T6V8W0XYZ"
    assert out["service"] == "unit"


def test_settings_empty_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("FL_SOVEREIGN_MODE", "false")
    s = Settings(_env_file=None)
    assert s.anthropic_api_key is None
    assert not s.cloud_enabled
