"""Guarded async HTTP client: the ``ctx.http`` implementation.

Every hop goes through ``validate_url`` and ``resolve_and_check``. Redirects
are followed manually (at most 10) and re-checked. The body is capped
(5 MB by default) after decompression, and the decompressor is bounded too.

IP pinning works at two layers:

* **URL level (direct mode).** The request is sent to the IP literal we
  resolved and checked, with ``Host`` set to the real hostname and the httpx
  ``sni_hostname`` request extension set, so TLS still verifies the
  certificate against the hostname. httpx never resolves a name, so DNS
  rebinding between check and connect is impossible.
* **Socket level (defence in depth).** The transport's httpcore network
  backend refuses any ``connect_tcp`` whose host is not an allowed IP literal
  (direct mode), or that is not the configured egress proxy (proxy mode).

Proxy mode (``proxy="http://egress:3128"``): httpcore 1.0.9 ignores
``sni_hostname`` inside CONNECT tunnels and uses the origin host for TLS. So
the client keeps the hostname in the URL, pre-checks every hop itself, and
relies on the egress proxy (which runs the same guard) to resolve, check and
pin. See the PR notes for T-003.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import typing
import zlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType

import httpcore
import httpx

from .ssrf import (
    DEFAULT_POLICY,
    BlockReason,
    CanonicalTarget,
    GuardPolicy,
    IPAddress,
    Resolver,
    SSRFBlocked,
    ip_block_reason,
    resolve_and_check,
    validate_url,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_TIMEOUT_S",
    "FetchFailReason",
    "FetchFailed",
    "FetchResult",
    "GuardedHTTPClient",
    "Hop",
    "OnBlock",
    "PinnedNetworkBackend",
    "ProxyOnlyNetworkBackend",
    "safe_fetch",
    "set_default_on_block",
]

DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # THREAT_MODEL / T-003: 5 MB hard cap
DEFAULT_MAX_REDIRECTS = 10  # T-003 / T-004: at most 10 redirects
DEFAULT_TIMEOUT_S = 6.0  # sandbox total budget; signals pass their own smaller budget
USER_AGENT = "FalconLensChecker/0.1 (+defensive URL checker)"

_ALLOWED_METHODS = frozenset({"GET", "HEAD"})  # the checker never submits anything
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_HEADER_SUBSET = (
    "content-type",
    "content-length",
    "content-language",
    "content-encoding",
    "content-disposition",
    "last-modified",
    "etag",
    "server",
    "date",
    "cache-control",
    "x-frame-options",
    "content-security-policy",
    "strict-transport-security",
    "refresh",
)

OnBlock = Callable[[BlockReason], None]
_log = logging.getLogger(__name__)


class FetchFailReason(StrEnum):
    """Non-policy failures (the target misbehaved or was unreachable)."""

    TIMEOUT = "timeout"
    CONNECT_ERROR = "connect_error"
    PROTOCOL_ERROR = "protocol_error"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    DECODE_ERROR = "decode_error"


class FetchFailed(Exception):
    def __init__(self, reason: FetchFailReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


@dataclass(frozen=True)
class Hop:
    url: str  #: canonical URL requested at this hop (hostname form, never the IP form)
    status: int
    ip: str  #: the IP that was pinned for this hop


@dataclass(frozen=True)
class FetchResult:
    status: int
    final_url: str
    redirect_chain: tuple[Hop, ...]  #: every request made, first to last (final hop included)
    headers: Mapping[str, str]  #: allow-listed subset, lower-case names
    body: bytes  #: decoded body, at most max_bytes
    resolved_ip: str  #: IP pinned for the final hop


# ------------------------------------------------------------- metric hook


def _noop(_reason: BlockReason) -> None:
    return None


_default_on_block: OnBlock = _noop


def set_default_on_block(hook: OnBlock | None) -> None:
    """Install the process-wide block hook (observability wires
    ``fl_ssrf_blocked_total{reason}`` here once the T-014 registry lands)."""
    global _default_on_block
    _default_on_block = hook or _noop


def _emit(hook: OnBlock | None, reason: BlockReason) -> None:
    try:
        (hook or _default_on_block)(reason)
    except Exception:  # noqa: BLE001 - a metrics bug must never open the guard or mask the block
        _log.warning("on_block hook failed", exc_info=True)


# ---------------------------------------------------------- socket layer


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Only connects to allowed IP literals on allowed ports. Never resolves."""

    def __init__(
        self,
        policy: GuardPolicy = DEFAULT_POLICY,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._policy = policy
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        h = host.strip("[]")
        try:
            ipaddress.ip_address(h)
        except ValueError as exc:
            raise SSRFBlocked(BlockReason.NOT_PINNED, "connect to hostname refused") from exc
        if port not in self._policy.allowed_ports:
            raise SSRFBlocked(BlockReason.PORT, str(port))
        reason = ip_block_reason(h)
        if reason is not None:
            raise SSRFBlocked(reason, f"connect {h}")
        return await self._inner.connect_tcp(
            h,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise SSRFBlocked(BlockReason.SCHEME, "unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class ProxyOnlyNetworkBackend(httpcore.AsyncNetworkBackend):
    """Only connects to the configured egress proxy host:port."""

    def __init__(
        self,
        proxy_host: str,
        proxy_port: int,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._target = (proxy_host.lower(), proxy_port)
        self._inner = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if (host.lower(), port) != self._target:
            raise SSRFBlocked(BlockReason.NOT_PINNED, "only the egress proxy may be dialled")
        return await self._inner.connect_tcp(
            host,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise SSRFBlocked(BlockReason.SCHEME, "unix socket")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _build_transport(policy: GuardPolicy, proxy: str | None) -> httpx.AsyncHTTPTransport:
    """An httpx transport whose httpcore pool uses our network backend.

    httpx 0.28.1 does not expose ``network_backend`` on AsyncHTTPTransport, so
    we replace its private ``_pool`` with an equivalent pool. A unit test pins
    this behaviour so an httpx upgrade that breaks it fails loudly.
    """
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    ssl_context = httpx.create_ssl_context(trust_env=False)
    if proxy is None:
        transport._pool = httpcore.AsyncConnectionPool(  # private: see docstring
            ssl_context=ssl_context,
            network_backend=PinnedNetworkBackend(policy),
            retries=0,
            max_connections=20,
            max_keepalive_connections=0,  # no reuse: every hop gets a fresh, freshly pinned socket
            keepalive_expiry=0.0,
        )
    else:
        purl = httpx.URL(proxy)
        if purl.scheme != "http" or purl.port is None:
            raise ValueError("proxy must be http://host:port")
        transport._pool = httpcore.AsyncHTTPProxy(  # private: see docstring
            proxy_url=httpcore.URL(scheme=b"http", host=purl.raw_host, port=purl.port, target=b"/"),
            ssl_context=ssl_context,
            network_backend=ProxyOnlyNetworkBackend(purl.host, purl.port),
            max_connections=20,
            max_keepalive_connections=0,
            keepalive_expiry=0.0,
        )
    return transport


# --------------------------------------------------------------- body


async def _read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    declared = resp.headers.get("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared) > max_bytes:
        raise SSRFBlocked(BlockReason.RESPONSE_TOO_LARGE, f"content-length {declared}")
    encoding = resp.headers.get("content-encoding", "identity").strip().lower()
    decomp: typing.Any = None
    if encoding in ("gzip", "x-gzip"):
        decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decomp = zlib.decompressobj(32 + zlib.MAX_WBITS)
    elif encoding not in ("identity", ""):
        raise FetchFailed(FetchFailReason.UNSUPPORTED_ENCODING, encoding[:32])

    out = bytearray()
    raw_total = 0
    async for chunk in resp.aiter_raw():
        raw_total += len(chunk)
        if raw_total > max_bytes:
            raise SSRFBlocked(BlockReason.RESPONSE_TOO_LARGE, "raw body")
        if decomp is None:
            out += chunk
            continue
        buf = chunk
        try:
            while buf:
                # Bounded output per call defeats decompression bombs.
                out += decomp.decompress(buf, max_bytes - len(out) + 1)
                if len(out) > max_bytes:
                    raise SSRFBlocked(BlockReason.RESPONSE_TOO_LARGE, "decoded body")
                buf = decomp.unconsumed_tail
        except zlib.error as exc:
            raise FetchFailed(FetchFailReason.DECODE_ERROR, encoding) from exc
    if len(out) > max_bytes:
        raise SSRFBlocked(BlockReason.RESPONSE_TOO_LARGE, "body")
    return bytes(out)


def _next_method(method: str, status: int) -> str:
    if status == 303 and method != "HEAD":
        return "GET"
    if status in (301, 302) and method not in ("GET", "HEAD"):
        return "GET"
    return method


# --------------------------------------------------------------- client


class GuardedHTTPClient:
    """Long-lived guarded client (the ``ctx.http`` implementation).

    ``transport`` is for tests only (for example ``httpx.MockTransport``); in
    production leave it ``None`` so the pinned network backend is used.
    """

    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        policy: GuardPolicy = DEFAULT_POLICY,
        on_block: OnBlock | None = None,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._resolver = resolver
        self._policy = policy
        self._on_block = on_block
        self._proxy = proxy
        self._ua = user_agent
        self._client = httpx.AsyncClient(
            transport=transport or _build_transport(policy, proxy),
            trust_env=False,  # never pick up HTTP(S)_PROXY / NO_PROXY mounts
            follow_redirects=False,
        )

    async def __aenter__(self) -> typing.Self:
        return self

    async def __aexit__(
        self,
        et: type[BaseException] | None,
        ev: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
    ) -> FetchResult:
        """Fetch ``url`` under the egress policy.

        Raises ``SSRFBlocked`` (policy, ``on_block`` is called) or
        ``FetchFailed`` (timeout, network, decoding).
        """
        max_bytes = max(0, min(max_bytes, DEFAULT_MAX_BYTES))
        max_redirects = max(0, min(max_redirects, DEFAULT_MAX_REDIRECTS))
        try:
            m = method.upper()
            if m not in _ALLOWED_METHODS:
                raise SSRFBlocked(BlockReason.METHOD, m[:16])
            async with asyncio.timeout(timeout):
                return await self._fetch(url, m, max_bytes, timeout, max_redirects)
        except SSRFBlocked as exc:
            _emit(self._on_block, exc.reason)
            raise
        except TimeoutError as exc:
            raise FetchFailed(FetchFailReason.TIMEOUT) from exc
        except httpx.TimeoutException as exc:
            raise FetchFailed(FetchFailReason.TIMEOUT) from exc
        except (httpx.ConnectError, httpx.ProxyError) as exc:
            raise FetchFailed(FetchFailReason.CONNECT_ERROR, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise FetchFailed(FetchFailReason.PROTOCOL_ERROR, type(exc).__name__) from exc

    async def _fetch(
        self, url: str, method: str, max_bytes: int, timeout: float, max_redirects: int
    ) -> FetchResult:
        hops: list[Hop] = []
        current = url
        while True:
            target = validate_url(current, self._policy)
            ips = await resolve_and_check(target, self._resolver, self._policy)
            ip = ips[0]
            resp = await self._send(method, target, ip, timeout)
            try:
                location = resp.headers.get("location")
                if resp.status_code in _REDIRECT_STATUSES and location:
                    hops.append(Hop(url=target.url, status=resp.status_code, ip=ip.compressed))
                    if len(hops) > max_redirects:
                        raise SSRFBlocked(BlockReason.TOO_MANY_REDIRECTS, str(len(hops)))
                    try:
                        current = str(httpx.URL(target.url).join(location))
                    except (httpx.InvalidURL, ValueError, UnicodeError) as exc:
                        raise SSRFBlocked(BlockReason.INVALID_URL, "bad Location") from exc
                    method = _next_method(method, resp.status_code)
                    continue
                body = b"" if method == "HEAD" else await _read_capped(resp, max_bytes)
                hops.append(Hop(url=target.url, status=resp.status_code, ip=ip.compressed))
                headers = {k: resp.headers[k] for k in _HEADER_SUBSET if k in resp.headers}
                return FetchResult(
                    status=resp.status_code,
                    final_url=target.url,
                    redirect_chain=tuple(hops),
                    headers=headers,
                    body=body,
                    resolved_ip=ip.compressed,
                )
            finally:
                await resp.aclose()

    async def _send(
        self, method: str, target: CanonicalTarget, ip: IPAddress, timeout: float
    ) -> httpx.Response:
        headers = {
            "Host": target.host_header,
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
        }
        extensions: dict[str, typing.Any] = {}
        if self._proxy is None:
            req_url = target.url_for_ip(ip)  # pinned: httpx never resolves
            if target.scheme == "https":
                extensions["sni_hostname"] = target.host
        else:
            req_url = target.url  # the egress proxy re-resolves, re-checks and pins
        request = httpx.Request(method, req_url, headers=headers, extensions=extensions)
        request.extensions["timeout"] = httpx.Timeout(timeout).as_dict()
        return await self._client.send(request, stream=True)


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT_S,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    resolver: Resolver | None = None,
    policy: GuardPolicy = DEFAULT_POLICY,
    on_block: OnBlock | None = None,
    proxy: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    """One-shot guarded fetch. See ``GuardedHTTPClient.fetch``."""
    async with GuardedHTTPClient(
        resolver=resolver,
        policy=policy,
        on_block=on_block,
        proxy=proxy,
        transport=transport,
    ) as client:
        return await client.fetch(
            url,
            method=method,
            max_bytes=max_bytes,
            timeout=timeout,
            max_redirects=max_redirects,
        )
