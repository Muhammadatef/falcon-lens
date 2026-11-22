"""Falcon Lens MCP server entrypoint."""

from __future__ import annotations

from falcon_core.service import run
from falcon_mcp.app import build_app

app = build_app()

if __name__ == "__main__":
    run(app)
