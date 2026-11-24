"""Operator-only runtime switch for the language-model route: GET/PUT /v1/admin/llm-route.

The choice is stored in Redis (``fl:llm_route``); the worker and the Sentinel re-read it every few seconds, so a
change needs no restart. ``FL_SOVEREIGN_MODE=1`` locks the route to ``local``. The route never touches a score.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field
from redis.exceptions import RedisError

from falcon_api.auth import Principal
from falcon_api.problem import PROBLEM_RESPONSES, Problem
from falcon_core.config import Settings
from falcon_core.llm.route import (
    LOCAL_MODELS,
    ROUTE_MODES,
    RouteSetting,
    effective_mode,
    parse_mode,
    read_setting,
    write_setting,
)

log = logging.getLogger("falcon.api.admin")

RouteModeName = Literal["cloud_with_local_fallback", "local", "cloud_only", "auto"]
LocalModelName = Literal["inkling-2-mini-chat", "qwen3.8:27b"]


class LlmRouteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: RouteModeName = Field(description="Requested route mode.")
    local_model: LocalModelName | None = Field(default=None, description="Local model; null keeps FL_LOCAL_MODEL.")


class LlmRoute(BaseModel):
    mode: RouteModeName = Field(description="Requested mode (runtime choice, else the FL_LLM_ROUTE default).")
    effective_mode: Literal["cloud_with_local_fallback", "local", "cloud_only"] = Field(
        description="What actually runs after the key and sovereign checks."
    )
    local_model: str
    local_models: list[str]
    modes: list[str]
    cloud_available: bool = Field(description="An Anthropic API key is configured.")
    sovereign_locked: bool = Field(description="FL_SOVEREIGN_MODE=1: the route is fixed to local.")
    source: Literal["runtime", "environment"]
    updated_at: str | None = None
    updated_by: str | None = None
    note: str | None = Field(default=None, description="Why the effective mode differs from the requested one.")


class PublicLlmRoute(BaseModel):
    """Read-only, in GET /v1/meta."""

    mode: Literal["cloud_with_local_fallback", "local", "cloud_only"]
    local_model: str
    sovereign: bool


def _state(settings: Settings, stored: RouteSetting | None) -> LlmRoute:
    sovereign = settings.fl_sovereign_mode
    cloud = settings.anthropic_api_key is not None
    requested = stored.mode if stored else (parse_mode(settings.fl_llm_route) or "auto")
    eff, why = effective_mode(requested, sovereign=sovereign, cloud_available=cloud)
    pick = stored.local_model if stored and stored.local_model else settings.fl_local_model
    return LlmRoute(
        mode=requested,
        effective_mode=eff,
        local_model=pick,
        local_models=list(LOCAL_MODELS),
        modes=list(ROUTE_MODES),
        cloud_available=cloud,
        sovereign_locked=sovereign,
        source="runtime" if stored else "environment",
        updated_at=stored.updated_at if stored else None,
        updated_by=stored.updated_by if stored else None,
        note=why,
    )


async def load_route(settings: Settings, redis: Any) -> LlmRoute:
    stored: RouteSetting | None = None
    if redis is not None:
        try:
            stored = await read_setting(redis)
        except RedisError:
            log.warning("llm route store unavailable; showing the environment default")
    return _state(settings, stored)


async def public_route(settings: Settings, redis: Any) -> dict[str, Any]:
    s = await load_route(settings, redis)
    return PublicLlmRoute(mode=s.effective_mode, local_model=s.local_model, sovereign=s.sovereign_locked).model_dump()


def register(
    app: FastAPI,
    *,
    settings: Settings,
    get_redis: Callable[[], Any],
    require: Callable[[str], Callable[..., Awaitable[Principal]]],
) -> None:
    operator = require("operator")

    @app.get("/v1/admin/llm-route", tags=["admin"], response_model=LlmRoute, responses=PROBLEM_RESPONSES)
    async def get_llm_route(_p: Principal = Depends(operator)) -> LlmRoute:  # noqa: B008
        """Current language-model route (operator scope)."""
        return await load_route(settings, get_redis())

    @app.put("/v1/admin/llm-route", tags=["admin"], response_model=LlmRoute, responses=PROBLEM_RESPONSES)
    async def put_llm_route(body: LlmRouteIn, request: Request, p: Principal = Depends(operator)) -> LlmRoute:  # noqa: B008
        """Switch the route at runtime (operator scope, audit-logged). Takes effect in a few seconds."""
        if settings.fl_sovereign_mode and body.mode != "local":
            raise Problem(409, "sovereign-locked", "Sovereign mode is on", detail="The route is fixed to local.")
        redis = get_redis()
        if redis is None:
            raise Problem(503, "route-store-unavailable", "Route store unavailable")
        try:
            before = await read_setting(redis)
            new = await write_setting(redis, body.mode, body.local_model, p.label or p.key_id)
        except RedisError as exc:
            raise Problem(503, "route-store-unavailable", "Route store unavailable") from exc
        was = before.mode if before else "default"
        request.state.audit_note = f"llm-route {was} -> {new.mode}; local_model={new.local_model or 'default'}"
        return _state(settings, new)
