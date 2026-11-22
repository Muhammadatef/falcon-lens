"""Falcon Lens sandbox (skeleton: health only; Playwright visits land with builder-sandbox).

The service sits on the internal ``sandbox`` and ``sandbox_ctl`` networks only. Everything except
the health probes requires the shared bearer token ``FL_SANDBOX_TOKEN`` (held by the worker).
"""

from __future__ import annotations

from falcon_core.config import get_settings
from falcon_core.service import create_app, run

_token = get_settings().fl_sandbox_token

app = create_app(
    "sandbox",
    title="Falcon Lens sandbox",
    protect=True,
    token=_token.get_secret_value() if _token else None,
)

if __name__ == "__main__":
    run(app)
