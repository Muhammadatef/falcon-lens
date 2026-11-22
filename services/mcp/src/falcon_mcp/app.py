"""ASGI app: /healthz /readyz /metrics plus the MCP streamable-HTTP endpoint at /mcp behind a static bearer."""

from __future__ import annotations

import hmac
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from falcon_core.config import Settings, get_settings
from falcon_core.service import create_app
from falcon_mcp.server import ApiClient, build_mcp

log = logging.getLogger("falcon.mcp")


class BearerMiddleware:
    """Static bearer for /mcp. Fail-closed: with no token configured every /mcp request is refused."""

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        self.app, self.token = app, token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.app(scope, receive, send)
            return
        got = ""
        for k, v in scope["headers"]:
            if k == b"authorization":
                got = v.decode("latin-1")
        ok = (
            bool(self.token)
            and got.lower().startswith("bearer ")
            and hmac.compare_digest(got[7:].strip().encode(), (self.token or "").encode())
        )
        if ok:
            await self.app(scope, receive, send)
            return
        body = json.dumps(
            {"type": "urn:falcon-lens:problem:unauthorized", "title": "Unauthorized", "status": 401}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"www-authenticate", b'Bearer realm="falcon-lens-mcp"'),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def _allowed_hosts(settings: Settings) -> list[str]:
    hosts = ["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "mcp", "mcp:*", "testserver"]
    pub = urlsplit(settings.fl_public_base_url).hostname
    if pub:
        hosts += [pub, f"{pub}:*"]
    hosts += [h.strip() for h in os.environ.get("FL_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return hosts


def build_app(settings: Settings | None = None, *, api_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    settings = settings or get_settings()
    api = ApiClient(
        os.environ.get("FL_API_URL", "http://api:8000"), os.environ.get("FL_MCP_SERVICE_KEY"), transport=api_transport
    )
    mcp = build_mcp(api)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=_allowed_hosts(settings),
            allowed_origins=[settings.fl_public_base_url.rstrip("/")],
        ),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield
        await api.close()

    app = create_app("mcp", lifespan=lifespan, title="Falcon Lens MCP")
    token = settings.fl_mcp_bearer_token.get_secret_value() if settings.fl_mcp_bearer_token else None
    if token is None:
        log.warning("FL_MCP_BEARER_TOKEN unset: /mcp refuses every request")
    app.mount("/", mcp_app)  # after /healthz etc.; the mounted app's own lifespan never runs
    app.add_middleware(BearerMiddleware, token=token)
    return app
