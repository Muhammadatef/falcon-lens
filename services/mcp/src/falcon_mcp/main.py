"""Falcon Lens MCP server entrypoint.

What it does:
    Builds the MCP server app with `falcon_mcp.app.build_app()` (health and metrics endpoints plus the MCP
    streamable-HTTP endpoint at /mcp, protected by a static bearer token) and serves it with uvicorn on port 8000.

When to use it:
    You do not run it by hand; the `mcp` container starts it.

How to run:
    make up                                   (direct: uv run python -m falcon_mcp.main)

Inputs:
    Env FL_MCP_BEARER_TOKEN (without a token every /mcp request is refused), FL_MCP_SERVICE_KEY (used when it
    calls the API), FL_API_URL (default http://api:8000) and FL_MCP_ALLOWED_HOSTS (extra allowed Host names).

Outputs / side effects:
    Listens on 0.0.0.0:8000 and calls the Falcon Lens API over HTTP on behalf of MCP clients. It writes no files.
"""

from __future__ import annotations

from falcon_core.service import run
from falcon_mcp.app import build_app

app = build_app()

if __name__ == "__main__":
    run(app)
