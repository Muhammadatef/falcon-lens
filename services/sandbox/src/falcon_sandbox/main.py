"""Falcon Lens sandbox: /render (features only) and /capture (snapshot for evals replay).

Internal service, reachable from the worker over ``sandbox_ctl`` only; every call needs the demo
key. Raw HTML and screenshots never appear in a response: they go to the snapshot volume.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from falcon_core.service import create_app, run
from falcon_core.signals.page.cloaking import compare_profiles
from falcon_core.signals.page.features import (
    PROFILES,
    ProfileFeatures,
    ProfileName,
    RenderFeatures,
)

from .browser import SandboxBrowser
from .compat import to_flat
from .policy import TOTAL_TIMEOUT_S, check_target
from .settings import Settings
from .storage import SnapshotStore


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=4096)
    verdict_id: str | None = Field(default=None, max_length=64)
    profiles: list[ProfileName] = Field(default_factory=lambda: list(PROFILES), min_length=1)
    visual: bool = Field(default=False, description="allow fonts/media (visual brand match)")


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(max_length=4096)
    profile: ProfileName = "desktop_en"


class CaptureResponse(BaseModel):
    """Hashes only; the files live under data/private/snapshots/<snapshot_id>/."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    dom_sha256: str
    screenshot_sha256: str | None
    status: int | None
    redirect_count: int
    error: str | None = None


def build_app(settings: Settings | None = None, browser: SandboxBrowser | None = None) -> FastAPI:
    cfg = settings or Settings.from_env()
    sb = browser or SandboxBrowser(cfg)
    store = SnapshotStore(cfg.snapshot_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await sb.start()
        try:
            yield
        finally:
            await sb.stop()

    app = create_app(
        "sandbox", title="Falcon Lens sandbox", lifespan=lifespan, deps={"browser": sb.ready}
    )

    def auth(x_sandbox_key: Annotated[str | None, Header()] = None) -> None:
        if (
            not cfg.api_key
            or not x_sandbox_key
            or not hmac.compare_digest(x_sandbox_key, cfg.api_key)
        ):
            raise HTTPException(401, "invalid sandbox key")

    def refuse(url: str) -> None:
        reason = check_target(url, cfg.guard)
        if reason:
            raise HTTPException(400, {"error": "blocked", "reason": reason})

    @app.post("/render", dependencies=[Depends(auth)])
    async def render(req: RenderRequest) -> dict[str, Any]:
        refuse(req.url)
        t0 = time.monotonic()
        names = list(dict.fromkeys(req.profiles))
        results = await asyncio.gather(
            *(sb.visit(req.url, n, visual=req.visual, keep_artifacts=False) for n in names)
        )
        profiles: dict[ProfileName, ProfileFeatures] = {}
        for n, r in zip(names, results, strict=True):
            if r.screenshot:  # stored privately; never returned
                store.save_screenshot(r.screenshot)
            profiles[n] = r.features
        cloaking = (
            compare_profiles(profiles["mobile_ar"], profiles["desktop_en"])
            if "mobile_ar" in profiles and "desktop_en" in profiles
            else None
        )
        out = RenderFeatures(
            url=req.url[:512],
            profiles=profiles,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        if cloaking is not None:
            out.cloaking = cloaking
        return to_flat(out, req.verdict_id)

    @app.post("/capture", response_model=CaptureResponse, dependencies=[Depends(auth)])
    async def capture(req: CaptureRequest) -> CaptureResponse:
        refuse(req.url)
        r = await sb.visit(req.url, req.profile, visual=True, keep_artifacts=True)
        if r.dom is None:
            raise HTTPException(502, {"error": "capture_failed", "reason": r.features.error})
        sid, dom_sha, shot_sha = store.save_snapshot(
            dom=r.dom,
            screenshot=r.screenshot,
            redirects=r.redirects,
            network=r.features.network.model_dump(),
            features=r.features.model_dump(),
        )
        return CaptureResponse(
            snapshot_id=sid,
            dom_sha256=dom_sha,
            screenshot_sha256=shot_sha,
            status=r.features.status,
            redirect_count=max(0, len(r.features.redirect_chain) - 1),
            error=r.features.error,
        )

    app.state.timeout_s = TOTAL_TIMEOUT_S
    return app


if __name__ == "__main__":  # pragma: no cover
    run(build_app())
