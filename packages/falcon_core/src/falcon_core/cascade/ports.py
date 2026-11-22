"""Interfaces the cascade depends on, with offline stubs.

- Feed mirror: the registered T0 signal ``rep.openphish`` (``signals.reputation``) reads ``ctx.mirror``.
- ``SandboxClient``: sandbox ``/render`` (T-009, builder-sandbox). HTTP client + stub.
- ``Extractor``: quarantined LLM extractor hook (T-024). Not wired yet: ``None`` by default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx

from falcon_core.cascade.models import SandboxFeatures
from falcon_core.scoring.evidence import Evidence


class SandboxError(Exception):
    """The sandbox could not render the page (timeout, refused, bad response)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SandboxClient(Protocol):
    async def render(self, url: str, verdict_id: str) -> SandboxFeatures: ...


class HttpSandboxClient:
    """POST ``{base_url}/render`` with ``{"url", "verdict_id"}``; response = features dict.

    The sandbox is an internal service on ``sandbox_ctl``; the URL itself is fetched by the sandbox
    through the egress proxy, never by the worker.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_s: float = 7.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # The sandbox (and service.protect) accept "Authorization: Bearer <FL_SANDBOX_TOKEN>".
        headers = {"Authorization": f"Bearer {token}", "X-Sandbox-Key": token} if token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
            follow_redirects=False,
        )

    async def render(self, url: str, verdict_id: str) -> SandboxFeatures:
        try:
            resp = await self._client.post("/render", json={"url": url, "verdict_id": verdict_id})
        except httpx.TimeoutException as exc:
            raise SandboxError("timeout") from exc
        except httpx.HTTPError as exc:
            raise SandboxError(f"unreachable:{type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise SandboxError(f"http_{resp.status_code}")
        try:
            body: Any = resp.json()
        except ValueError as exc:
            raise SandboxError("bad_json") from exc
        if isinstance(body, Mapping) and isinstance(body.get("features"), Mapping):
            body = body["features"]
        try:
            return SandboxFeatures.model_validate(body)
        except ValueError as exc:
            raise SandboxError("bad_shape") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class StubSandboxClient:
    """Returns canned features per URL (or a default), or raises ``SandboxError``."""

    def __init__(
        self,
        by_url: Mapping[str, SandboxFeatures] | None = None,
        default: SandboxFeatures | None = None,
        error: str | None = None,
    ) -> None:
        self.by_url = dict(by_url or {})
        self.default = default
        self.error = error
        self.calls: list[str] = []

    async def render(self, url: str, verdict_id: str) -> SandboxFeatures:
        self.calls.append(url)
        if self.error is not None:
            raise SandboxError(self.error)
        features = self.by_url.get(url, self.default)
        if features is None:
            raise SandboxError("no_stub")
        return features


class Extractor(Protocol):
    """T-024 quarantined extractor: sees spotlighted page text, returns structured evidence only.

    Its evidence must use ``source="llm:extractor"`` so the arbiter lets it only raise risk.
    """

    async def extract(self, features: SandboxFeatures, verdict_id: str) -> Sequence[Evidence]: ...
