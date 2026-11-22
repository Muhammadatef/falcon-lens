from fastapi.testclient import TestClient

from falcon_api.main import app


def test_version_and_health() -> None:
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/v1/version").json()["api"] == "v1"
