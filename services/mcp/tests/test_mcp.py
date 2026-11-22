from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import fakeredis
import httpx
import httpx2
import pytest
from fastapi import FastAPI, HTTPException
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr

from falcon_api.app import build_app as build_api
from falcon_api.intel import SentinelClient
from falcon_core.config import Settings
from falcon_mcp.app import build_app
from falcon_mcp.server import ApiClient, build_mcp

ROOT = Path(__file__).resolve().parents[3]
BEARER = "test-mcp-bearer"
SERVICE_KEY = "test-mcp-service-key"
TOOLS = {
    "check_url",
    "check_message",
    "check_email",
    "get_verdict",
    "list_campaigns",
    "list_incidents",
    "get_incident",
    "submit_report",
}


def make_incident(n: int) -> dict[str, Any]:
    return {
        "incident_id": f"inc_{n:026d}",
        "type": "campaign",
        "severity": "high",
        "status": "open",
        "brand_id": "falcon_demo_bank",
        "rule_ids": ["R1"],
        "indicators": [{"kind": "domain", "value_defanged": f"demo-{n}[.]test", "first_seen": "2026-11-22T01:00:00Z"}],
        "linked_verdicts": [],
        "timeline": [],
        "actions": [],
        "source": "synthetic",
        "created_at": "2026-11-22T01:00:00Z",
        "updated_at": f"2026-11-22T0{n}:00:00Z",
    }


def fake_sentinel(incidents: list[dict[str, Any]]) -> FastAPI:
    app = FastAPI()

    @app.get("/internal/incidents")
    async def lst() -> list[dict[str, Any]]:
        return incidents

    @app.get("/internal/incidents/{iid}")
    async def one(iid: str) -> dict[str, Any]:
        for i in incidents:
            if i["incident_id"] == iid:
                return i
        raise HTTPException(404)

    return app


def settings(**kw: Any) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        fl_api_key_pepper=SecretStr("pep"),
        fl_public_base_url="https://app.example.test",
        **kw,
    )


@pytest.fixture
def api_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FL_MCP_SERVICE_KEY", SERVICE_KEY)
    sentinel = SentinelClient(
        "http://sentinel", None, transport=httpx.ASGITransport(app=fake_sentinel([make_incident(1), make_incident(2)]))
    )
    return build_api(
        settings(fl_rate_limit_per_ip_per_min=100),
        redis=fakeredis.FakeAsyncRedis(decode_responses=True),
        sentinel=sentinel,
    )


@asynccontextmanager
async def mcp_client(api_app: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Client]:
    monkeypatch.setenv("FL_MCP_SERVICE_KEY", SERVICE_KEY)
    app = build_app(settings(fl_mcp_bearer_token=SecretStr(BEARER)), api_transport=httpx.ASGITransport(app=api_app))
    async with app.router.lifespan_context(app):
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://localhost",
            headers={"Authorization": f"Bearer {BEARER}"},
        )
        async with http, Client(streamable_http_client("http://localhost/mcp", http_client=http)) as c:  # type: ignore[arg-type]
            yield c


async def test_tool_list_and_schemas(api_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async with mcp_client(api_app, monkeypatch) as c:
        tools = (await c.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    by = {t.name: t for t in tools}
    assert all(t.description and len(t.description) > 30 for t in tools)
    assert by["check_url"].input_schema["required"] == ["url"]
    assert by["check_url"].input_schema["properties"]["url"]["maxLength"] == 4096
    assert by["get_verdict"].input_schema["properties"]["verdict_id"]["pattern"].startswith("^vd_")
    assert by["list_incidents"].annotations and by["list_incidents"].annotations.read_only_hint is True
    assert by["submit_report"].annotations and by["submit_report"].annotations.read_only_hint is False
    assert {t.name for t in tools} == set(
        json.loads((ROOT / "contracts" / "tools.schema.json").read_text())["mcp_tools"]
    )


async def test_call_list_incidents_and_submit_report(api_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    async with mcp_client(api_app, monkeypatch) as c:
        res = await c.call_tool("list_incidents", {"limit": 5})
        assert not res.is_error
        body = res.structured_content or json.loads(res.content[0].text)  # type: ignore[union-attr]
        assert len(body["items"]) == 2 and body["next_cursor"] is None
        rep = await c.call_tool("submit_report", {"kind": "message", "text": "demo text"})
        assert not rep.is_error
        assert (rep.structured_content or {})["report_id"].startswith("rpt_")
        bad = await c.call_tool("get_incident", {"incident_id": "inc_" + "9" * 26})
        assert bad.is_error and "Not found" in bad.content[0].text  # type: ignore[union-attr]


async def test_bearer_required(api_app: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_MCP_SERVICE_KEY", SERVICE_KEY)
    app = build_app(settings(fl_mcp_bearer_token=SecretStr(BEARER)))
    async with app.router.lifespan_context(app):  # noqa: SIM117
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as c:
            assert (await c.post("/mcp", json={})).status_code == 401
            r = await c.post("/mcp", json={}, headers={"Authorization": "Bearer wrong"})
            assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
            assert (await c.get("/healthz")).status_code == 200  # health stays open
    nobearer = build_app(settings())  # fail closed with no token configured
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=nobearer), base_url="http://localhost") as c:
        r = await c.post("/mcp", json={}, headers={"Authorization": "Bearer "})
        assert r.status_code == 401


async def test_in_memory_tool_error_has_no_secret() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"title": "Rate limit exceeded", "status": 429})

    api = ApiClient("http://api", "k", transport=httpx.MockTransport(boom))
    async with Client(build_mcp(api)) as c:
        res = await c.call_tool("list_campaigns", {})
    assert res.is_error and "Rate limit exceeded" in res.content[0].text  # type: ignore[union-attr]
