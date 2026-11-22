"""Falcon Lens API entrypoint."""

from __future__ import annotations

from falcon_api.app import build_app
from falcon_core.service import run

app = build_app()

if __name__ == "__main__":
    run(app)
