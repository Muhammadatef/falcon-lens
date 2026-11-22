"""Falcon Lens API entrypoint: builds the FastAPI app and serves it.

What it does:
    Creates the app with `build_app()` (routes live in falcon_api/app.py) and, when run directly, starts
    uvicorn on port 8000 via falcon_core.service.run.

When to use it:
    You do not run it by hand; the `api` container starts it. Tests and scripts import `app` from here.

How to run:
    make up                                   (starts the whole stack)
    uv run python -m falcon_api.main          (direct form; needs the env the app expects, see .env.example)

Inputs / outputs:
    Settings come from env vars (see packages/falcon_core config). Listens on 0.0.0.0:8000 inside the
    container; the gateway fronts it. This file itself writes nothing.
"""

from __future__ import annotations

from falcon_api.app import build_app
from falcon_core.service import run

app = build_app()

if __name__ == "__main__":
    run(app)
