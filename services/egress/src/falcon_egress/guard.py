"""Egress policy hook.

TODO(builder-security): replace ``check`` with the shared SSRF guard from
``falcon_core.security`` (RFC1918/loopback/link-local/metadata/internal-service-name blocks,
DNS-rebinding-safe resolution that pins the connect IP). Keep the signature stable: the proxy
connects to the first address returned in ``Decision.addresses`` so the guard's resolution
is the one that is actually dialled.

This placeholder is fail-closed but minimal: ports 80/443 only, and every resolved address
must be globally routable (``ipaddress.is_global``).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field

ALLOWED_PORTS = frozenset({80, 443})


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    addresses: list[str] = field(default_factory=list)


async def check(host: str, port: int) -> Decision:
    if port not in ALLOWED_PORTS:
        return Decision(False, f"port {port} not allowed")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError:
        return Decision(False, "dns resolution failed")
    addresses = [str(info[4][0]) for info in infos]
    if not addresses:
        return Decision(False, "no addresses")
    for addr in addresses:
        if not ipaddress.ip_address(addr.split("%")[0]).is_global:
            return Decision(False, "non-global address blocked")
    return Decision(True, "ok", addresses)
