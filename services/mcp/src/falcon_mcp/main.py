"""Falcon Lens MCP server (skeleton: health only; tools arrive with contracts/tools.schema.json)."""

from __future__ import annotations

from falcon_core.service import create_app, run

app = create_app("mcp", title="Falcon Lens MCP")

if __name__ == "__main__":
    run(app)
