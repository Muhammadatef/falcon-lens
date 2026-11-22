"""Falcon Lens MCP server entrypoint (skeleton: health only; tools arrive with contracts/tools.schema.json).

What it does:
    Creates a minimal service app named "mcp" (health and metrics endpoints only) and serves it with
    uvicorn on port 8000.

When to use it:
    You do not run it by hand; the `mcp` container starts it.

How to run:
    make up                                   (direct: uv run python -m falcon_mcp.main)

Inputs / outputs:
    No special env vars. No tools are exposed yet. Listens on 0.0.0.0:8000; writes nothing.
"""

from __future__ import annotations

from falcon_core.service import create_app, run

app = create_app("mcp", title="Falcon Lens MCP")

if __name__ == "__main__":
    run(app)
