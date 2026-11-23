"""GuardedHTTPClient.post forwards only allow-listed header names (API keys)."""

from __future__ import annotations

import httpx
import pytest
from test_policy import API, POST_POLICY, PUBLIC_V4, table

from falcon_core.security import GuardedHTTPClient


@pytest.mark.asyncio
async def test_post_forwards_only_allow_listed_headers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(b"{}"))

    async with GuardedHTTPClient(
        resolver=table({API: [PUBLIC_V4]}),
        policy=POST_POLICY,
        transport=httpx.MockTransport(handler),
    ) as c:
        await c.post(f"https://{API}/v1/host/", data={"host": "x"}, headers={"Auth-Key": "k1"})
        await c.post(f"https://{API}/v4/x", json={}, headers={"X-Goog-Api-Key": "k2"})
        for bad in ({"Authorization": "x"}, {"Host": "evil"}, {"Auth-Key": "a\r\nX: y"}):
            with pytest.raises(ValueError):
                await c.post(f"https://{API}/v1/host/", json={}, headers=bad)
    assert seen[0].headers["auth-key"] == "k1"
    assert seen[1].headers["x-goog-api-key"] == "k2"
    assert len(seen) == 2
