"""Per-request policy for the browser: decides allow/block without any I/O (unit-testable).

Layer 1 of the network defence (the egress proxy is layer 2): syntactic SSRF validation of every
URL, every redirect hop and every sub-resource, using the shared ``falcon_core.security`` guard.
DNS is resolved by the egress proxy, not here (the sandbox network has no DNS to the internet).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from falcon_core.security import GuardPolicy, SSRFBlocked, validate_url

MAX_REDIRECTS = 10
#: Cap on everything EXCEPT the main document (scripts, styles, images, frames), summed over the visit.
#: Once it is spent, further sub-resources are refused; the visit carries on (not an error).
MAX_TOTAL_BYTES = 5 * 1024 * 1024
#: The main document alone: kept up to this size, anything beyond is cut (``truncated``), not failed.
MAIN_DOC_MAX_BYTES = 8 * 1024 * 1024
#: A main document that DECLARES more than this (Content-Length) is refused unread: ``size_cap``.
MAIN_DOC_HARD_BYTES = 32 * 1024 * 1024
#: Wall-clock budget of one visit including extraction and hashing (docs/ARCHITECTURE.md: 6 s). The worker waits 7 s
#: (``sandbox_timeout_s``) and the p95 objective is 8 s end to end (RUNBOOK latency-burn).
TOTAL_TIMEOUT_S = 6.0
#: Navigation (redirect hops + reaching DOMContentLoaded) gets this much; the rest is reserved for extraction.
NAV_BUDGET_S = 4.5
#: One sub-resource may hold the page this long; a hung third-party script must not eat the whole budget.
SUBRESOURCE_TIMEOUT_S = 2.5
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

    @property
    def exhausted(self) -> bool:
        return self.total >= self.cap

    def would_exceed(self, n: int) -> bool:
        """Would adding ``n`` bytes pass the cap? Used BEFORE a body is read."""
        return self.total + max(0, n) > self.cap


def declared_length(headers: Mapping[str, str]) -> int | None:
    """Content-Length from response headers, if present and numeric."""
    for k, v in headers.items():
        if k.lower() == "content-length":
            try:
                return int(v)
            except ValueError:
                return None
    return None


def classify_fetch_error(message: str) -> str:
    """Map a transport failure to a stable sandbox ``error`` code (the cascade degrades on it)."""
    m = message.lower()
    if "enotfound" in m or "getaddrinfo" in m or "name_not_resolved" in m or "dns" in m:
        return "dns_failure"
    if "tunnel" in m or "proxy" in m or "407" in m or "403" in m:
        return "egress_blocked"
    if "econnrefused" in m or "connection refused" in m or "econnreset" in m:
        return "connect_failed"
    if "timeout" in m or "timed out" in m:
        return "timeout"
    if "certificate" in m or "ssl" in m or "tls" in m:
        return "tls_error"
    return "fetch_failed"


BLOCK_REASON_HEADER = "x-falcon-block-reason"
_REASON_RE = re.compile(r"[a-z0-9_]{1,40}")
_PROXY_STATUSES = {405: "egress_blocked", 407: "egress_blocked", 502: "egress_error"}


def proxy_refusal(status: int, headers: Mapping[str, str], body_len: int, via_proxy: bool) -> str | None:
    """Tell the egress proxy's own refusal apart from the target site's response.

    * ``X-Falcon-Block-Reason`` present (any status, any body): the proxy denied the request by
      policy (SSRF etc.) -> ``blocked_by_policy:<reason>`` (hard). If the value is not a clean
      reason token it fails closed to plain ``blocked_by_policy``. A target can only forge this
      header to make itself look blocked, never to look clean.
    * empty 403 with no content type and no header: the target's own refusal (bot protection)
      -> ``http_403_empty`` (a render failure the cascade may treat as soft).
    * empty 405/407 (CONNECT-only proxy, plain http) -> ``egress_blocked``; 502 -> ``egress_error``.
    Other target HTTP errors keep their normal path (the page is returned as-is)."""
    if not via_proxy:
        return None
    lowered = {k.lower(): v for k, v in headers.items()}
    if BLOCK_REASON_HEADER in lowered:
        reason = lowered[BLOCK_REASON_HEADER].strip().lower()
        return f"blocked_by_policy:{reason}" if _REASON_RE.fullmatch(reason) else "blocked_by_policy"
    if body_len or "content-type" in lowered:
        return None
    if status == 403:
        return "http_403_empty"
    return _PROXY_STATUSES.get(status)


def check_target(url: str, guard: GuardPolicy) -> str | None:
    """Reason string if ``url`` may not be visited at all, else None."""
    try:
        validate_url(url, guard)
    except SSRFBlocked as exc:
        return exc.reason.value
    return None
