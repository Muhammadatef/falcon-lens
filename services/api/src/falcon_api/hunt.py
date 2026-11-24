"""Hunt mode REST (docs/design/HUNTER.md section 6): GET /v1/hunt/candidates, GET/PUT /v1/admin/hunt, Meta.hunt.

The data lives in the Sentinel (hunt_candidates); the API proxies its /internal/hunt routes with the operator key.
The public feed returns only arbiter-confirmed candidates, defanged, with no prescore; everything else is a count.
Pause / resume writes the Redis key the scheduler checks before every outbound request, and is audit-logged.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request
from pydantic import ValidationError
from redis.exceptions import RedisError

from falcon_api.auth import Principal
from falcon_api.intel import SentinelClient, brand_display
from falcon_api.problem import PROBLEM_RESPONSES, Problem
from falcon_core.contracts.hunt import HuntAdmin, HuntAdminIn, HuntAdminItem, HuntFeed, HuntFeedItem, HuntMeta

log = logging.getLogger("falcon.api.hunt")
PAUSE_KEY = "fl:hunt:paused"
META_TIMEOUT_S = 1.5  # /v1/meta is public and must stay fast; a slow Sentinel gives `hunt: null`


def _feed_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    names = brand_display(str(raw.get("brand_id") or ""))
    try:
        item = HuntFeedItem.model_validate({**raw, "brand_name": {"ar": names[1], "en": names[0]} if names else None})
    except ValidationError:
        return None  # never pass through a row that does not match the public contract
    return item.model_dump(mode="json")


async def meta_block(sentinel: SentinelClient) -> dict[str, Any] | None:
    """Meta.hunt from the Sentinel; null when the Sentinel cannot be asked (never a guessed value)."""
    try:
        data = await asyncio.wait_for(sentinel._call("GET", "/internal/hunt"), META_TIMEOUT_S)  # noqa: SLF001
        return HuntMeta.model_validate({k: data.get(k) for k in HuntMeta.model_fields}).model_dump(mode="json")
    except (Problem, ValidationError, AttributeError, TimeoutError):
        return None


def register(
    app: FastAPI,
    *,
    get_sentinel: Callable[[], SentinelClient],
    get_redis: Callable[[], Any],
    require: Callable[[str], Callable[..., Awaitable[Principal]]],
) -> None:
    read = require("read")
    operator = require("operator")

    @app.get("/v1/hunt/candidates", tags=["hunt"], response_model=HuntFeed, responses=PROBLEM_RESPONSES)
    async def hunt_candidates(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        _p: Principal = Depends(read),  # noqa: B008
    ) -> dict[str, Any]:
        """Arbiter-confirmed hunt candidates (read scope): defanged, no prescore; other statuses as counts only."""
        data = await get_sentinel()._call("GET", "/internal/hunt/candidates", params={"view": "public", "limit": limit})  # noqa: SLF001
        rows = data.get("items", []) if isinstance(data, dict) else []
        items = [i for i in (_feed_item(r) for r in rows if isinstance(r, dict)) if i is not None]
        counts = data.get("counts", {}) if isinstance(data, dict) else {}
        return HuntFeed.model_validate({"items": items, "counts": counts}).model_dump(mode="json")

    async def admin_view() -> dict[str, Any]:
        s = get_sentinel()
        state = await s._call("GET", "/internal/hunt")  # noqa: SLF001
        cands = await s._call("GET", "/internal/hunt/candidates", params={"view": "operator", "limit": 200})  # noqa: SLF001
        rows = cands.get("items", []) if isinstance(cands, dict) else []
        items = []
        for r in rows:
            try:
                items.append(HuntAdminItem.model_validate(r).model_dump(mode="json"))
            except ValidationError:
                continue  # an off-contract row is dropped, never rendered
        body = {**(state if isinstance(state, dict) else {}), "items": items}
        try:
            return HuntAdmin.model_validate(body).model_dump(mode="json")
        except ValidationError as exc:
            raise Problem(502, "sentinel-error", "Sentinel returned an unexpected body") from exc

    @app.get("/v1/admin/hunt", tags=["admin"], response_model=HuntAdmin, responses=PROBLEM_RESPONSES)
    async def get_admin_hunt(_p: Principal = Depends(operator)) -> dict[str, Any]:  # noqa: B008
        """Hunt mode operator view (operator scope): all statuses, prescore (queue priority only), quotas."""
        return await admin_view()

    @app.put("/v1/admin/hunt", tags=["admin"], response_model=HuntAdmin, responses=PROBLEM_RESPONSES)
    async def put_admin_hunt(
        body: HuntAdminIn,
        request: Request,
        p: Principal = Depends(operator),  # noqa: B008
    ) -> dict[str, Any]:
        """Pause or resume hunting at runtime (operator scope, audit-logged). Takes effect before the next request."""
        redis = get_redis()
        if redis is None:
            raise Problem(503, "hunt-store-unavailable", "Hunt control unavailable")
        try:
            was = bool(await redis.get(PAUSE_KEY))
            if body.paused:
                await redis.set(PAUSE_KEY, f"{p.label or p.key_id}@{datetime.now(UTC).isoformat()}")
            else:
                await redis.delete(PAUSE_KEY)
        except RedisError as exc:
            raise Problem(503, "hunt-store-unavailable", "Hunt control unavailable") from exc
        request.state.audit_note = f"hunt paused {was} -> {body.paused}"
        return await admin_view()
