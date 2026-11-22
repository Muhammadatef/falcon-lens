# ruff: noqa: E501
"""RedirectResolver interface. Shortener expansion / redirect-chain following needs network, so it belongs to the
SSRF-guarded client (T-003). T1 lexical signals never fetch; this module only defines the contract and a stub."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class RedirectChain:
    start: str
    hops: tuple[str, ...] = field(default_factory=tuple)  # intermediate + final URLs in order
    resolved: bool = False  # False: nothing was fetched
    error: str | None = None

    @property
    def final(self) -> str:
        return self.hops[-1] if self.hops else self.start


class RedirectResolver(Protocol):
    async def resolve(self, url: str, max_hops: int = 5) -> RedirectChain:
        """Follow redirects via the SSRF-guarded client only (never directly)."""
        ...


class NullRedirectResolver:
    """Offline stub: returns the URL unchanged, ``resolved=False``."""

    async def resolve(self, url: str, max_hops: int = 5) -> RedirectChain:
        return RedirectChain(start=url, hops=(), resolved=False)
