"""Per-request policy for the browser: decides allow/block without any I/O (unit-testable).

Layer 1 of the network defence (the egress proxy is layer 2): syntactic SSRF validation of every
URL, every redirect hop and every sub-resource, using the shared ``falcon_core.security`` guard.
DNS is resolved by the egress proxy, not here (the sandbox network has no DNS to the internet).
"""

from __future__ import annotations

from dataclasses import dataclass

from falcon_core.security import GuardPolicy, SSRFBlocked, validate_url

MAX_REDIRECTS = 10
MAX_TOTAL_BYTES = 5 * 1024 * 1024
TOTAL_TIMEOUT_S = 6.0
SAFE_METHODS = frozenset({"GET", "HEAD"})
LOCAL_SCHEMES = ("data:", "blob:", "about:")
BLOCKED_ALWAYS = frozenset({"websocket", "eventsource", "manifest"})
BLOCKED_UNLESS_VISUAL = frozenset({"font", "media"})


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str = ""


@dataclass(frozen=True)
class RequestPolicy:
    guard: GuardPolicy
    visual: bool = False

    def decide(self, url: str, method: str, resource_type: str, redirect_depth: int = 0) -> Decision:
        if method.upper() not in SAFE_METHODS:
            return Decision(False, "method_not_get")  # NEVER send a form or script POST
        if url.startswith(LOCAL_SCHEMES):
            return Decision(True)
        if redirect_depth > MAX_REDIRECTS:
            return Decision(False, "too_many_redirects")
        if resource_type in BLOCKED_ALWAYS:
            return Decision(False, f"type_{resource_type}")
        if resource_type in BLOCKED_UNLESS_VISUAL and not self.visual:
            return Decision(False, f"type_{resource_type}")
        try:
            validate_url(url, self.guard)
        except SSRFBlocked as exc:
            return Decision(False, f"ssrf_{exc.reason.value}")
        return Decision(True)


class ByteBudget:
    """Running total of received bytes; ``add`` returns True once the cap is exceeded."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.total = 0

    def add(self, n: int) -> bool:
        self.total += max(0, n)
        return self.total > self.cap


def check_target(url: str, guard: GuardPolicy) -> str | None:
    """Reason string if ``url`` may not be visited at all, else None."""
    try:
        validate_url(url, guard)
    except SSRFBlocked as exc:
        return exc.reason.value
    return None
