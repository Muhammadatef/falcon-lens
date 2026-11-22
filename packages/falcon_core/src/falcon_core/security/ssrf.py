"""SSRF guard: URL validation, own DNS resolution, and IP policy.

This module is the single implementation of the outbound-network policy. It is
used by the guarded HTTP client (``falcon_core.security.http``) and is meant to
be reused by the egress CONNECT proxy (``services/egress``) so both layers apply
exactly the same rules (see DECISIONS.md, "one implementation").

Pipeline for every hop of every fetch:

1. ``validate_url(url)``: syntactic checks only, no I/O. It checks the scheme,
   userinfo, port, obfuscated numeric hosts and internal or special-use names,
   and returns a ``CanonicalTarget``.
2. ``resolve_and_check(target, resolver)``: our own DNS resolution. *Every*
   returned address must pass ``ip_block_reason``. A single bad record blocks
   the whole host, so a mixed public and private answer cannot win a race.
3. The caller connects to the returned IP (pinned), never to the hostname.

Nothing here raises anything except ``SSRFBlocked`` (policy) and ``ValueError``
for programmer errors.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import httpx

__all__ = [
    "DEFAULT_POLICY",
    "BlockReason",
    "CanonicalTarget",
    "GuardPolicy",
    "IPAddress",
    "Resolver",
    "SSRFBlocked",
    "check_host_port",
    "ip_reason_for_host",
    "resolve_host_port",
    "ip_block_reason",
    "is_ip_allowed",
    "resolve_and_check",
    "system_resolver",
    "validate_url",
]

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address

#: Async resolver: hostname -> list of IP address strings. Injected in tests.
Resolver = Callable[[str], Awaitable[Sequence[str]]]

MAX_URL_LENGTH = 4096  # THREAT_MODEL §D: URL 4 KB
MAX_HOST_LENGTH = 253


class BlockReason(StrEnum):
    """Typed block reasons. Values are the ``reason`` label of
    ``fl_ssrf_blocked_total``; keep them low-cardinality and stable."""

    SCHEME = "scheme"
    USERINFO = "userinfo"
    PORT = "port"
    INVALID_URL = "invalid_url"
    URL_TOO_LONG = "url_too_long"
    OBFUSCATED_IP = "obfuscated_ip"
    INTERNAL_NAME = "internal_name"
    LOOPBACK = "loopback"
    PRIVATE = "private"
    LINK_LOCAL = "link_local"
    METADATA = "metadata"
    CGNAT = "cgnat"
    IPV6_ULA = "ipv6_ula"
    RESERVED = "reserved"
    DNS_FAILURE = "dns_failure"
    NOT_PINNED = "not_pinned"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    REQUEST_TOO_LARGE = "request_too_large"
    EGRESS_DENIED = "egress_denied"  # the egress proxy refused (proxy mode)
    TOO_MANY_REDIRECTS = "too_many_redirects"
    RESPONSE_TOO_LARGE = "response_too_large"


class SSRFBlocked(Exception):
    """Raised when a URL, host, address or response violates the egress policy."""

    def __init__(self, reason: BlockReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


@dataclass(frozen=True)
class GuardPolicy:
    """Egress policy. The defaults are the production policy; tests and the
    fixture network may widen ``allow_hosts`` explicitly, never implicitly."""

    allowed_ports: frozenset[int] = frozenset({80, 443})
    #: Exact hostnames exempt from the internal-name check whose addresses may
    #: be private (RFC 1918, IPv6 ULA, CGNAT). Only for the internal
    #: "Falcon Demo Bank" fixture host. Empty in production.
    allow_hosts: frozenset[str] = field(default_factory=frozenset)
    #: Exact IPs an allow-listed host may additionally resolve to even though
    #: they are loopback, link-local, metadata or reserved. Empty by default:
    #: listing a host never opens metadata or loopback on its own.
    allow_host_ips: frozenset[str] = field(default_factory=frozenset)
    #: Exact hostnames that ``GuardedHTTPClient.post`` may POST to (https only).
    #: Empty by default; the reputation module passes its two API hosts.
    post_allow_hosts: frozenset[str] = field(default_factory=frozenset)


DEFAULT_POLICY = GuardPolicy()


@dataclass(frozen=True)
class CanonicalTarget:
    """A validated, canonicalised fetch target (one hop)."""

    url: str  #: canonical URL (lower-case scheme/host, default port elided, no fragment)
    scheme: str  #: "http" | "https"
    host: str  #: ASCII (IDNA) lower-case host without brackets or trailing dot
    port: int  #: effective port
    request_target: str  #: raw path + query, always starts with "/"
    ip: IPAddress | None  #: set when the host is an IP literal

    @property
    def host_header(self) -> str:
        h = f"[{self.host}]" if self.ip is not None and self.ip.version == 6 else self.host
        default = 443 if self.scheme == "https" else 80
        return h if self.port == default else f"{h}:{self.port}"

    def url_for_ip(self, ip: IPAddress) -> str:
        """The same request target, but addressed to a pinned IP literal."""
        h = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
        default = 443 if self.scheme == "https" else 80
        port = "" if self.port == default else f":{self.port}"
        return f"{self.scheme}://{h}{port}{self.request_target}"


# --------------------------------------------------------------------------- IPs

_V4 = ipaddress.IPv4Network
_V6 = ipaddress.IPv6Network

_METADATA_IPS: frozenset[IPAddress] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure/OCI/DO IMDS
        ipaddress.ip_address("169.254.170.2"),  # AWS ECS task metadata
        ipaddress.ip_address("169.254.170.23"),  # AWS EKS pod identity
        ipaddress.ip_address("100.100.100.200"),  # Alibaba Cloud
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS IPv6
        ipaddress.ip_address("fd00:ec2::23"),  # AWS EKS pod identity IPv6
    }
)

# Ordered: first match wins, so the more specific label is reported.
_V4_RULES: tuple[tuple[_V4, BlockReason], ...] = (
    (_V4("127.0.0.0/8"), BlockReason.LOOPBACK),
    (
        _V4("0.0.0.0/8"),
        BlockReason.RESERVED,
    ),  # "this network"; 0.0.0.0 hits localhost on Linux
    (_V4("10.0.0.0/8"), BlockReason.PRIVATE),
    (_V4("172.16.0.0/12"), BlockReason.PRIVATE),
    (_V4("192.168.0.0/16"), BlockReason.PRIVATE),
    (_V4("169.254.0.0/16"), BlockReason.LINK_LOCAL),
    (_V4("100.64.0.0/10"), BlockReason.CGNAT),
    (_V4("192.0.0.0/24"), BlockReason.RESERVED),  # IETF protocol assignments
    (_V4("192.0.2.0/24"), BlockReason.RESERVED),  # TEST-NET-1
    (_V4("198.18.0.0/15"), BlockReason.RESERVED),  # benchmarking
    (_V4("198.51.100.0/24"), BlockReason.RESERVED),  # TEST-NET-2
    (_V4("203.0.113.0/24"), BlockReason.RESERVED),  # TEST-NET-3
    (_V4("224.0.0.0/4"), BlockReason.RESERVED),  # multicast
    (_V4("240.0.0.0/4"), BlockReason.RESERVED),  # reserved + broadcast
)

_V6_RULES: tuple[tuple[_V6, BlockReason], ...] = (
    (_V6("::1/128"), BlockReason.LOOPBACK),
    (_V6("::/128"), BlockReason.RESERVED),
    (_V6("fe80::/10"), BlockReason.LINK_LOCAL),
    (_V6("fec0::/10"), BlockReason.PRIVATE),  # deprecated site-local
    (_V6("fc00::/7"), BlockReason.IPV6_ULA),
    (_V6("ff00::/8"), BlockReason.RESERVED),  # multicast
    (_V6("64:ff9b:1::/48"), BlockReason.RESERVED),  # local-use NAT64
    (_V6("2001:db8::/32"), BlockReason.RESERVED),  # documentation
    (
        _V6("2001::/23"),
        BlockReason.RESERVED,
    ),  # IETF protocol assignments, incl. Teredo 2001::/32
    (_V6("100::/64"), BlockReason.RESERVED),  # discard-only
)
_V6_GLOBAL_UNICAST = _V6("2000::/3")
_V6_COMPAT = _V6("::/96")  # deprecated IPv4-compatible, not routable
_NAT64_WKP = _V6("64:ff9b::/96")


def _coerce_ip(ip: str | IPAddress) -> IPAddress:
    if isinstance(ip, ipaddress.IPv4Address | ipaddress.IPv6Address):
        return ip
    return ipaddress.ip_address(ip.strip("[]"))


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """IPv4 address tunnelled inside an IPv6 one (mapped, 6to4, NAT64, compat).

    Teredo (2001::/32) is not unwrapped; it is blocked outright as reserved."""
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64_WKP:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if int(ip) >> 32 == 0 and int(ip) > 1:  # deprecated IPv4-compatible ::a.b.c.d
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def ip_block_reason(ip: str | IPAddress) -> BlockReason | None:
    """Return why ``ip`` must not be contacted, or ``None`` if it is public.

    Accepts strings (with or without IPv6 brackets) or ``ipaddress`` objects.
    Unparseable input is reported as ``INVALID_URL`` rather than raising.
    """
    try:
        addr = _coerce_ip(ip)
    except ValueError:
        return BlockReason.INVALID_URL
    if addr in _METADATA_IPS:
        return BlockReason.METADATA
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.scope_id:
            return BlockReason.LINK_LOCAL
        inner = _embedded_v4(addr)
        if inner is not None:
            # Unwrapping may only make the decision stricter: judge the inner
            # IPv4 first, then still refuse the non-routable compat range.
            inner_reason = ip_block_reason(inner)
            if inner_reason is not None:
                return inner_reason
            if addr in _V6_COMPAT:
                return BlockReason.RESERVED
            return None
        for net6, reason in _V6_RULES:
            if addr in net6:
                return reason
        if addr not in _V6_GLOBAL_UNICAST or not addr.is_global:
            return BlockReason.RESERVED
        return None
    for net4, reason in _V4_RULES:
        if addr in net4:
            return reason
    if not addr.is_global:
        return BlockReason.RESERVED
    return None


def is_ip_allowed(ip: str | IPAddress) -> bool:
    """True only for publicly routable unicast addresses. For the egress proxy."""
    return ip_block_reason(ip) is None


#: Reasons an allow-listed (fixture) host may override. Never metadata,
#: loopback, link-local or reserved, unless the exact IP is in allow_host_ips.
_LISTED_HOST_OVERRIDABLE = frozenset({BlockReason.PRIVATE, BlockReason.IPV6_ULA, BlockReason.CGNAT})


def ip_reason_for_host(
    host: str, ip: str | IPAddress, policy: GuardPolicy = DEFAULT_POLICY
) -> BlockReason | None:
    """Like ``ip_block_reason`` but honours ``policy.allow_hosts`` for ``host``.

    This is the one function every layer (URL, socket, proxy) uses to decide
    whether ``ip`` may be dialled on behalf of ``host``.
    """
    reason = ip_block_reason(ip)
    if reason is None or host not in policy.allow_hosts:
        return reason
    if reason in _LISTED_HOST_OVERRIDABLE:
        return None
    try:
        addr = _coerce_ip(ip)
        if any(addr == _coerce_ip(x) for x in policy.allow_host_ips):
            return None
    except ValueError:
        return reason
    return reason


# ------------------------------------------------------------------------- hosts

#: Names that resolve to internal things on Docker, k8s, home and corporate
#: networks, plus RFC 6761/6762/7686/8375 special-use names.
_INTERNAL_SUFFIXES: tuple[str, ...] = (
    "localhost",
    "local",
    "localdomain",
    "internal",
    "intranet",
    "lan",
    "home",
    "corp",
    "private",
    "home.arpa",
    "arpa",  # in-addr.arpa / ip6.arpa are never web hosts
    "test",
    "example",
    "invalid",
    "onion",
    "alt",
    "svc",
    "cluster.local",
    "consul",
    "docker",
)

_LABEL_RE = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")
# inet_aton() accepts each part as decimal, 0-prefixed octal or 0x hex.
_NUMERIC_PART_RE = re.compile(r"^(?:0x[0-9a-f]*|[0-9]+)$")
_CANONICAL_V4_RE = re.compile(
    r"^(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$"
)


def _is_internal_name(host: str) -> bool:
    if "." not in host:  # single label: redis, postgres, api, egress, ...
        return True
    return any(host == s or host.endswith("." + s) for s in _INTERNAL_SUFFIXES)


def _reject_numeric_host(host: str) -> None:
    """Anything numeric-looking that is not canonical dotted-quad is an
    obfuscated IP (2130706433, 0177.0.0.1, 0x7f.1, 127.1) or garbage that some
    resolver (inet_aton) would still turn into an address. A real DNS name
    never has an all-numeric (or 0x-hex) last label."""
    if _CANONICAL_V4_RE.match(host):
        return
    labels = host.split(".")
    if all(_NUMERIC_PART_RE.match(p) for p in labels) or _NUMERIC_PART_RE.match(labels[-1]):
        raise SSRFBlocked(BlockReason.OBFUSCATED_IP, host)


def _check_host(host: str, policy: GuardPolicy) -> IPAddress | None:
    """Validate an (already lower-cased, IDNA-encoded, de-bracketed) host.

    Returns the IP for IP-literal hosts, ``None`` for DNS names. Raises
    ``SSRFBlocked`` otherwise.
    """
    if not host or len(host) > MAX_HOST_LENGTH:
        raise SSRFBlocked(BlockReason.INVALID_URL, "bad host length")
    if ":" in host:  # IPv6 literal (brackets already stripped)
        try:
            ip6 = ipaddress.IPv6Address(host)
        except ValueError as exc:
            raise SSRFBlocked(BlockReason.INVALID_URL, "bad IPv6 literal") from exc
        reason = ip_reason_for_host(host, ip6, policy)
        if reason is not None:
            raise SSRFBlocked(reason, host)
        return ip6

    labels = host.split(".")
    if _CANONICAL_V4_RE.match(host):
        ip4 = ipaddress.IPv4Address(host)
        reason = ip_reason_for_host(host, ip4, policy)
        if reason is not None:
            raise SSRFBlocked(reason, host)
        return ip4
    _reject_numeric_host(host)

    if any(not _LABEL_RE.match(label) for label in labels):
        raise SSRFBlocked(BlockReason.INVALID_URL, "bad host label")
    if host in policy.allow_hosts:
        return None
    if _is_internal_name(host):
        raise SSRFBlocked(BlockReason.INTERNAL_NAME, host)
    return None


def check_host_port(host: str, port: int, policy: GuardPolicy = DEFAULT_POLICY) -> IPAddress | None:
    """Host + port check for the egress proxy's CONNECT ``host:port``.

    Returns the IP for IP-literal hosts, ``None`` for names (which the caller
    must then pass through ``resolve_and_check``).
    """
    return _check_host(_normalise_host_port(host, port, policy), policy)


def _normalise_host_port(host: str, port: int, policy: GuardPolicy) -> str:
    if port not in policy.allowed_ports:
        raise SSRFBlocked(BlockReason.PORT, str(port))
    h = host.strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    h = h.rstrip(".")
    try:
        if ":" not in h:
            _reject_numeric_host(h)
            h = httpx.URL(f"http://{h}/").raw_host.decode("ascii").lower()
    except (httpx.InvalidURL, UnicodeError) as exc:
        raise SSRFBlocked(BlockReason.INVALID_URL, "bad host") from exc
    return h


# --------------------------------------------------------------------------- URLs

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_FORBIDDEN_CHARS_RE = re.compile(r"[\x00-\x20\x7f\\]")


def validate_url(url: str, policy: GuardPolicy = DEFAULT_POLICY) -> CanonicalTarget:
    """Validate ``url`` syntactically (no I/O) and return its canonical target.

    Raises ``SSRFBlocked`` with a typed reason on any violation.
    """
    if not isinstance(url, str):
        raise SSRFBlocked(BlockReason.INVALID_URL, "not a string")
    raw = url.strip()
    if len(raw) > MAX_URL_LENGTH:
        raise SSRFBlocked(BlockReason.URL_TOO_LONG, str(len(raw)))
    m = _SCHEME_RE.match(raw)
    if m is None:
        raise SSRFBlocked(BlockReason.INVALID_URL, "no scheme")
    scheme = m.group(1).lower()
    if scheme not in ("http", "https"):
        raise SSRFBlocked(BlockReason.SCHEME, scheme)
    # Whitespace, control chars and backslashes cause parser differentials
    # (browsers treat "\" as "/"), so refuse them outright.
    if _FORBIDDEN_CHARS_RE.search(raw):
        raise SSRFBlocked(BlockReason.INVALID_URL, "forbidden character")
    rest = raw[m.end() :]
    if not rest.startswith("//"):
        raise SSRFBlocked(BlockReason.INVALID_URL, "no authority")
    authority = re.split(r"[/?#]", rest[2:], maxsplit=1)[0]
    if "@" in authority or "%40" in authority.lower():
        raise SSRFBlocked(BlockReason.USERINFO)
    if not authority:
        raise SSRFBlocked(BlockReason.INVALID_URL, "empty host")

    # Pre-check numeric hosts on the raw text: httpx rejects some forms
    # (0177.0.0.1) with a generic error, and we want the typed reason.
    if not authority.startswith("["):
        _reject_numeric_host(authority.rsplit(":", 1)[0].lower().rstrip("."))

    try:
        parsed = httpx.URL(raw)
        host = parsed.raw_host.decode("ascii")  # IDNA-encoded, brackets stripped
    except (httpx.InvalidURL, ValueError, UnicodeError) as exc:
        raise SSRFBlocked(BlockReason.INVALID_URL, "unparseable") from exc
    if parsed.userinfo:
        raise SSRFBlocked(BlockReason.USERINFO)
    host = host.lower().rstrip(".")
    if "%" in host:  # percent-encoded or zone-id hosts
        raise SSRFBlocked(BlockReason.INVALID_URL, "encoded host")

    default_port = 443 if scheme == "https" else 80
    port = parsed.port if parsed.port is not None else default_port
    if port not in policy.allowed_ports:
        raise SSRFBlocked(BlockReason.PORT, str(port))

    ip = _check_host(host, policy)

    request_target = parsed.raw_path.decode("ascii") or "/"
    if not request_target.startswith("/"):
        request_target = "/" + request_target
    tmp = CanonicalTarget(
        url="",
        scheme=scheme,
        host=host,
        port=port,
        request_target=request_target,
        ip=ip,
    )
    canonical = f"{scheme}://{tmp.host_header}{request_target}"
    return CanonicalTarget(
        url=canonical,
        scheme=scheme,
        host=host,
        port=port,
        request_target=request_target,
        ip=ip,
    )


# ---------------------------------------------------------------------------- DNS


async def system_resolver(host: str) -> list[str]:
    """Resolve via the OS resolver on the running loop (A + AAAA)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    out: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr = str(sockaddr[0])
        if addr not in out:
            out.append(addr)
    return out


async def resolve_and_check(
    target: CanonicalTarget,
    resolver: Resolver | None = None,
    policy: GuardPolicy = DEFAULT_POLICY,
) -> list[IPAddress]:
    """Resolve ``target.host`` ourselves and check every address.

    Returns the allowed addresses (first one should be pinned). If *any*
    record is disallowed the host is blocked, which defeats mixed answers.
    """
    if target.ip is not None:
        return [target.ip]
    res = resolver or system_resolver
    try:
        answers = await res(target.host)
    except (OSError, UnicodeError) as exc:
        raise SSRFBlocked(BlockReason.DNS_FAILURE, target.host) from exc
    ips: list[IPAddress] = []
    for a in answers:
        try:
            ips.append(_coerce_ip(a))
        except ValueError as exc:
            raise SSRFBlocked(BlockReason.DNS_FAILURE, "bad address in answer") from exc
    if not ips:
        raise SSRFBlocked(BlockReason.DNS_FAILURE, target.host)
    for ip in ips:
        reason = ip_reason_for_host(target.host, ip, policy)
        if reason is not None:
            raise SSRFBlocked(reason, f"{target.host} -> {ip.compressed}")
    return ips


async def resolve_host_port(
    host: str,
    port: int,
    resolver: Resolver | None = None,
    policy: GuardPolicy = DEFAULT_POLICY,
) -> list[IPAddress]:
    """Check ``host:port`` and resolve it ourselves (the egress proxy's CONNECT
    path). Returns the addresses to dial; the caller must dial one of these,
    never the name."""
    h = _normalise_host_port(host, port, policy)
    ip = _check_host(h, policy)
    target = CanonicalTarget(
        url="",
        scheme="https" if port == 443 else "http",
        host=h,
        port=port,
        request_target="/",
        ip=ip,
    )
    return await resolve_and_check(target, resolver, policy)
