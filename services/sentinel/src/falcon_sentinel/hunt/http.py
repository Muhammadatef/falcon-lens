"""The only HTTP clients the hunt may build (a test fails if any other module under hunt/ constructs one).

* ``HuntHTTP``: outbound, bound to ``FL_HUNT_PROXY`` (the `hunt-egress` proxy, allow-list crt.sh + the DoH host).
  It refuses to start without a proxy (no direct internet), checks the host against the same allow-list in
  process, never follows redirects, caps the body (4 MB), runs the pause guard before every request, and ignores
  proxy variables from the environment (``trust_env=False``).
* ``api_client``: internal, to the Falcon Lens API only (``POST /v1/check/url`` with the hunt key). No proxy.

Not built on ``falcon_core.security.http.GuardedHTTPClient``: that client caps every request at 6 s, and crt.sh
answers in 4-15 s (HUNTER.md section 9). The SSRF guard still runs in the egress proxy (DECISIONS.md).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 4 * 1024 * 1024
TIMEOUT_S = 30.0
USER_AGENT = "FalconLensHunt/0.1 (+defensive look-alike monitor)"

Guard = Callable[[], Awaitable[None]]


class HostNotAllowed(Exception):
    pass


class ResponseTooLarge(Exception):
    pass


@dataclass(frozen=True)
class JsonResponse:
    status: int
    data: Any  # parsed JSON, or None when the body was not JSON
    headers: Mapping[str, str]


async def _no_guard() -> None:
    return None


class HuntHTTP:
    def __init__(
        self,
        *,
        proxy: str | None,
        allow_hosts: tuple[str, ...],
        guard: Guard = _no_guard,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        if transport is None and not proxy:
            raise ValueError("hunt HTTP needs FL_HUNT_PROXY: the hunt has no direct route to the internet")
        self.allow_hosts = tuple(h.lower().strip(".") for h in allow_hosts)
        self.guard = guard
        self.max_bytes = max_bytes
        self.requests = 0
        self._client = httpx.AsyncClient(
            proxy=None if transport is not None else proxy,
            transport=transport,
            timeout=timeout_s,
            follow_redirects=False,
            trust_env=False,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )

    def host_allowed(self, host: str) -> bool:
        h = host.lower().rstrip(".")
        return any(h == d or h.endswith("." + d) for d in self.allow_hosts)

    async def get_json(
        self, url: str, params: Mapping[str, str] | None = None, headers: Mapping[str, str] | None = None
    ) -> JsonResponse:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or not self.host_allowed(parts.hostname):
            raise HostNotAllowed(parts.hostname or "")
        await self.guard()  # pause / kill switch: checked before every outbound request
        self.requests += 1
        async with self._client.stream("GET", url, params=params, headers=headers) as resp:
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > self.max_bytes:
                    raise ResponseTooLarge(str(len(buf)))
            try:
                data = json.loads(bytes(buf)) if buf else None
            except ValueError:
                data = None
            return JsonResponse(resp.status_code, data, {k.lower(): v for k, v in resp.headers.items()})

    async def aclose(self) -> None:
        await self._client.aclose()


def api_client(base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """Internal client for the Falcon Lens API (never the internet)."""
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        transport=transport,
        timeout=15.0,
        follow_redirects=False,
        trust_env=False,
        headers={"X-API-Key": api_key, "X-Falcon-Client": "sentinel-hunt"},
    )
