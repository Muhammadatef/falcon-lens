"""Falcon Lens sandbox (skeleton: health only; Playwright visits land with builder-sandbox)."""

from __future__ import annotations

from falcon_core.service import create_app, run

app = create_app("sandbox", title="Falcon Lens sandbox")

if __name__ == "__main__":
    run(app)
