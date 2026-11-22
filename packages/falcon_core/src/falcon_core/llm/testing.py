"""Deterministic stub providers for tests (used by this package's tests and by the cascade's)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from falcon_core.llm.accounting import Usage
from falcon_core.llm.config import Route
from falcon_core.llm.providers import ProviderError, ProviderRequest, ProviderResponse

Reply = str | ProviderError | Callable[[ProviderRequest], str]


@dataclass
class ScriptedProvider:
    """Returns scripted replies in order (the last one repeats). Records every request.

    A reply can be a string, a ``ProviderError`` to raise, or a callable of the request.
    ``delay_s`` simulates latency (for timeout tests).
    """

    route: Route
    replies: Sequence[Reply] = ("{}",)
    delay_s: float = 0.0
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=100, output_tokens=20))
    requests: list[ProviderRequest] = field(default_factory=list)

    async def complete(self, req: ProviderRequest) -> ProviderResponse:
        self.requests.append(req)
        idx = min(len(self.requests) - 1, len(self.replies) - 1)
        reply = self.replies[idx]
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if isinstance(reply, ProviderError):
            raise reply
        text = reply(req) if callable(reply) else reply
        return ProviderResponse(text=text, usage=self.usage, model=req.model)

    @property
    def calls(self) -> int:
        return len(self.requests)
