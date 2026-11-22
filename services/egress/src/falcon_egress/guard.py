"""Egress policy: a thin adapter over the shared SSRF guard (``falcon_core.security``).

There is one implementation (DECISIONS: "one implementation"). The proxy does
its own resolution through the guard and dials only ``Decision.addresses[0]``,
so the address that was checked is the address that is connected (pinned).
That holds for CONNECT tunnels and for plain-HTTP absolute-form requests.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from falcon_core.security import (
    BlockReason,
    GuardPolicy,
    Resolver,
    SSRFBlocked,
    resolve_and_check,
    resolve_host_port,
    validate_url,
)

ALLOWED_PORTS = frozenset({80, 443})


def policy_from_env() -> GuardPolicy:
    """Production policy. ``FL_EGRESS_ALLOW_HOSTS`` (comma-separated exact host
    names) is only for the internal "Falcon Demo Bank" fixture network. It is
    empty by default, and listing a host still never opens metadata or loopback."""
    raw = os.environ.get("FL_EGRESS_ALLOW_HOSTS", "")
    hosts = frozenset(h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip())
    return GuardPolicy(allowed_ports=ALLOWED_PORTS, allow_hosts=hosts)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    addresses: list[str] = field(default_factory=list)
    #: Only set by ``check_url``: the canonical Host header and origin-form target.
    host_header: str = ""
    request_target: str = ""
    port: int = 0


def _deny(exc: SSRFBlocked) -> Decision:
    return Decision(False, exc.reason.value)


async def check(
    host: str,
    port: int,
    *,
    resolver: Resolver | None = None,
    policy: GuardPolicy | None = None,
) -> Decision:
    """Decide a CONNECT ``host:port``. ``reason`` is a ``BlockReason`` value."""
    try:
        ips = await resolve_host_port(host, port, resolver, policy or policy_from_env())
    except SSRFBlocked as exc:
        return _deny(exc)
    return Decision(True, "ok", [ip.compressed for ip in ips], port=port)


async def check_url(
    url: str,
    *,
    resolver: Resolver | None = None,
    policy: GuardPolicy | None = None,
) -> Decision:
    """Decide a plain-HTTP absolute-form request target (``GET http://h/p``)."""
    pol = policy or policy_from_env()
    try:
        target = validate_url(url, pol)
        if target.scheme != "http":
            # https must use CONNECT; absolute-form https would make us the TLS client.
            raise SSRFBlocked(BlockReason.SCHEME, "absolute-form https")
        ips = await resolve_and_check(target, resolver, pol)
    except SSRFBlocked as exc:
        return _deny(exc)
    return Decision(
        True,
        "ok",
        [ip.compressed for ip in ips],
        host_header=target.host_header,
        request_target=target.request_target,
        port=target.port,
    )
