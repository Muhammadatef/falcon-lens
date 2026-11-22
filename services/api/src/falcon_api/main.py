"""Falcon Lens API (skeleton). Endpoints land in later task cards."""

from __future__ import annotations

from falcon_core.config import get_settings
from falcon_core.service import create_app, run

settings = get_settings()

deps: dict[str, str] = {}
if settings.database_url:
    deps["postgres"] = settings.database_url.get_secret_value()
if settings.redis_url:
    deps["redis"] = settings.redis_url

app = create_app("api", deps=deps, title="Falcon Lens API")


@app.get("/v1/version", tags=["meta"])
async def version() -> dict[str, str]:
    return {"service": "falcon-api", "api": "v1", "env": settings.fl_env}


if __name__ == "__main__":
    run(app)
