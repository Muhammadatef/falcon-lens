"""GET/PUT /v1/admin/llm-route: operator only, validated, audited, shared through Redis."""

from __future__ import annotations

import httpx

from falcon_core.llm.route import RedisRouteSource

from .conftest import OPERATOR_KEY, SANDBOX_KEY
from .test_integration import Env, api, env, key  # noqa: F401  (fixtures)

URL = "/v1/admin/llm-route"


async def test_non_operator_is_rejected(api: httpx.AsyncClient, env: Env) -> None:  # noqa: F811
    assert (await api.get(URL)).status_code == 401
    assert (await api.put(URL, json={"mode": "local"})).status_code == 401
    assert (await api.get(URL, headers=key(env.read_key))).status_code == 403
    assert (await api.put(URL, json={"mode": "local"}, headers=key(SANDBOX_KEY))).status_code == 403
    assert await env.redis.get("fl:llm_route") is None


async def test_put_validates_audits_and_workers_pick_it_up(api: httpx.AsyncClient, env: Env) -> None:  # noqa: F811
    r = await api.get(URL, headers=key(OPERATOR_KEY))
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "environment" and "qwen3.8:27b" in body["local_models"]
    for bad in ({"mode": "evil"}, {"mode": "local", "local_model": "gpt-9"}, {"mode": "local", "x": 1}):
        assert (await api.put(URL, json=bad, headers=key(OPERATOR_KEY))).status_code == 422
    r = await api.put(URL, json={"mode": "local", "local_model": "qwen3.8:27b"}, headers=key(OPERATOR_KEY))
    assert r.status_code == 200
    assert r.json()["effective_mode"] == "local" and r.json()["local_model"] == "qwen3.8:27b"
    assert r.json()["source"] == "runtime"
    notes = [row["note"] for row in env.audit.rows if row["method"] == "PUT" and row["path"] == URL]
    assert notes and "llm-route default -> local" in str(notes[-1])
    # A worker/sentinel router reading the same Redis sees it.
    setting = await RedisRouteSource(env.redis, ttl_s=0).get()
    assert setting is not None and setting.mode == "local" and setting.local_model == "qwen3.8:27b"
    # Public meta shows the active route, read-only.
    meta = (await api.get("/v1/meta")).json()
    assert meta["llm_route"] == {"mode": "local", "local_model": "qwen3.8:27b", "sovereign": False}
