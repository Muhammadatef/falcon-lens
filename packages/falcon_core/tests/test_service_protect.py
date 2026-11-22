from __future__ import annotations

from fastapi.testclient import TestClient

from falcon_core.service import create_app


def test_protected_app_requires_bearer_except_health() -> None:
    client = TestClient(create_app("unit", protect=True, token="s3cret"))  # noqa: S106
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_protected_app_without_token_fails_closed() -> None:
    client = TestClient(create_app("unit", protect=True, token=None))
    assert client.get("/metrics").status_code == 503
    assert client.get("/healthz").status_code == 200
