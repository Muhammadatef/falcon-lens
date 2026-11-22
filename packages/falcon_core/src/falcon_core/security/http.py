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

The socket layer learns the logical hostname of the current request through
a ``ContextVar`` that is set only around our own ``_send``. That is how an exact
``GuardPolicy.allow_hosts`` entry (the internal fixture host) can reach a
private address while every other host on the same IP is still refused.

POST (``GuardedHTTPClient.post``) is allowed only to exact hosts in
``GuardPolicy.post_allow_hosts`` over https, with a 64 KB request body cap
and no redirect following.

Proxy mode (``proxy="http://egress:3128"``): httpcore 1.0.9 ignores
``sni_hostname`` inside CONNECT tunnels and uses the origin host for TLS. So
the client keeps the hostname in the URL, pre-checks every hop itself, and
relies on the egress proxy (which runs the same guard) to resolve, check and
pin. See the PR notes for T-003.
"""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import json as jsonlib
import logging
import typing
import urllib.parse
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
    ip_reason_for_host,
    resolve_and_check,
    validate_url,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_REDIRECTS",
    "DEFAULT_MAX_REQUEST_BYTES",
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
DEFAULT_MAX_REQUEST_BYTES = 64 * 1024  # POST body cap (reputation API lookups only)
USER_AGENT = "FalconLensChecker/0.1 (+defensive URL checker)"

_ALLOWED_METHODS = frozenset({"GET", "HEAD"})  # fetch() never submits anything
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
_T = typing.TypeVar("_T")


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
    #: every request made, first to last (final hop included)
    redirect_chain: tuple[Hop, ...]
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

#: Logical hostname of the request that GuardedHTTPClient is currently sending.
#: httpcore dials inside the caller's task, so the backend sees this value.
#: It is only used to honour exact ``allow_hosts`` entries; ``None`` means strict.
_DIAL_HOST: contextvars.ContextVar[str | None] = contextvars.ContextVar("falcon_security_dial_host", default=None)


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
        reason = ip_reason_for_host(_DIAL_HOST.get() or "", h, self._policy)
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


def _build_transport(
    policy: GuardPolicy,
    proxy: str | None,
    inner: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncHTTPTransport:
    """An httpx transport whose httpcore pool uses our network backend.

    httpx 0.28.1 does not expose ``network_backend`` on AsyncHTTPTransport, so
    we replace its private ``_pool`` with an equivalent pool. A unit test pins
    this behaviour so an httpx upgrade that breaks it fails loudly. ``inner``
    replaces the real socket backend (tests only).
    """
    transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)
    ssl_context = httpx.create_ssl_context(trust_env=False)
    if proxy is None:
        transport._pool = httpcore.AsyncConnectionPool(  # private: see docstring
            ssl_context=ssl_context,
            network_backend=PinnedNetworkBackend(policy, inner),
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
            network_backend=ProxyOnlyNetworkBackend(purl.host, purl.port, inner),
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


def _clamp_timeout(timeout: float) -> float:
    """Callers may lower the time budget but never raise it above the default."""
    if not timeout > 0:  # 0, negative and NaN fall back to the default
        return DEFAULT_TIMEOUT_S
    return min(timeout, DEFAULT_TIMEOUT_S)


def _subset(resp: httpx.Response) -> dict[str, str]:
    return {k: resp.headers[k] for k in _HEADER_SUBSET if k in resp.headers}


# --------------------------------------------------------------- client


class GuardedHTTPClient:
    """Long-lived guarded client (the ``ctx.http`` implementation).

    ``transport`` is for tests only (for example ``httpx.MockTransport``); in
    production leave it ``None`` so the pinned network backend is used.
    Requests go straight to the transport, not through ``httpx.AsyncClient``.
    So there are no cookies, no auth, no environment proxies, no event hooks and no
    httpx-side redirect handling.
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
        self._transport: httpx.AsyncBaseTransport = transport or _build_transport(policy, proxy)

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
        await self._transport.aclose()

    def _block(self, reason: BlockReason, detail: str = "") -> SSRFBlocked:
        _emit(self._on_block, reason)
        return SSRFBlocked(reason, detail)

    async def _guarded(self, timeout: float, coro: typing.Awaitable[_T]) -> _T:
        """Run ``coro`` under the total deadline and map every failure to
        ``SSRFBlocked`` or ``FetchFailed`` (the documented contract)."""
        try:
            async with asyncio.timeout(timeout):
                return await coro
        except SSRFBlocked as exc:
            _emit(self._on_block, exc.reason)
            raise
        except TimeoutError as exc:
            raise FetchFailed(FetchFailReason.TIMEOUT) from exc
        except httpx.TimeoutException as exc:
            raise FetchFailed(FetchFailReason.TIMEOUT) from exc
        except httpx.ProxyError as exc:
            if str(exc).startswith("403"):  # CONNECT refused by the egress guard
                raise self._block(BlockReason.EGRESS_DENIED, "CONNECT 403") from exc
            raise FetchFailed(FetchFailReason.CONNECT_ERROR, type(exc).__name__) from exc
        except httpx.ConnectError as exc:
            raise FetchFailed(FetchFailReason.CONNECT_ERROR, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise FetchFailed(FetchFailReason.PROTOCOL_ERROR, type(exc).__name__) from exc
        except httpx.StreamError as exc:
            raise FetchFailed(FetchFailReason.PROTOCOL_ERROR, type(exc).__name__) from exc
        except (httpx.InvalidURL, UnicodeError) as exc:
            # Attacker-controlled response data that httpx refuses to model.
            raise self._block(BlockReason.INVALID_URL, type(exc).__name__) from exc

    async def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: float = DEFAULT_TIMEOUT_S,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
    ) -> FetchResult:
        """Fetch ``url`` (GET or HEAD) under the egress policy.

        Raises ``SSRFBlocked`` (policy, and ``on_block`` is called) or
        ``FetchFailed`` (timeout, network, decoding).
        """
        max_bytes = max(0, min(max_bytes, DEFAULT_MAX_BYTES))
        max_redirects = max(0, min(max_redirects, DEFAULT_MAX_REDIRECTS))
        timeout = _clamp_timeout(timeout)
        m = method.upper()
        if m not in _ALLOWED_METHODS:
            raise self._block(BlockReason.METHOD_NOT_ALLOWED, m[:16])
        return await self._guarded(timeout, self._fetch(url, m, max_bytes, timeout, max_redirects))

    async def post(
        self,
        url: str,
        *,
        json: typing.Any = None,
        data: Mapping[str, str] | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> FetchResult:
        """POST a small JSON or form body to an explicitly allow-listed API host.

        Rules: https only. The host must be an exact entry in ``policy.post_allow_hosts``,
        otherwise this raises ``SSRFBlocked(method_not_allowed)``. The body is at most 64 KB
        (``request_too_large`` otherwise). Resolution and pinning are the same as ``fetch``.
        Redirects are *not* followed: a 3xx is returned as-is.
        """
        if json is not None and data is not None:
            raise ValueError("pass json or data, not both")
        max_bytes = max(0, min(max_bytes, DEFAULT_MAX_BYTES))
        timeout = _clamp_timeout(timeout)
        return await self._guarded(timeout, self._post(url, json, data, max_bytes, timeout))

    async def _post(
        self,
        url: str,
        json_body: typing.Any,
        data: Mapping[str, str] | None,
        max_bytes: int,
        timeout: float,
    ) -> FetchResult:
        target = validate_url(url, self._policy)
        if target.host not in self._policy.post_allow_hosts:
            raise SSRFBlocked(BlockReason.METHOD_NOT_ALLOWED, f"POST {target.host}")
        if target.scheme != "https":
            raise SSRFBlocked(BlockReason.SCHEME, "POST requires https")
        if data is not None:
            content = urllib.parse.urlencode(dict(data)).encode("ascii")
            ctype = "application/x-www-form-urlencoded"
        else:
            content = jsonlib.dumps(json_body, separators=(",", ":"), ensure_ascii=False).encode()
            ctype = "application/json"
        if len(content) > DEFAULT_MAX_REQUEST_BYTES:
            raise SSRFBlocked(BlockReason.REQUEST_TOO_LARGE, str(len(content)))
        ips = await resolve_and_check(target, self._resolver, self._policy)
        ip = ips[0]
        resp = await self._send("POST", target, ip, timeout, content, ctype)
        try:
            self._raise_if_proxy_denied(resp)
            body = await _read_capped(resp, max_bytes)
            hop = Hop(url=target.url, status=resp.status_code, ip=ip.compressed)
            return FetchResult(
                status=resp.status_code,
                final_url=target.url,
                redirect_chain=(hop,),
                headers=_subset(resp),
                body=body,
                resolved_ip=ip.compressed,
            )
        finally:
            await resp.aclose()

    async def _fetch(self, url: str, method: str, max_bytes: int, timeout: float, max_redirects: int) -> FetchResult:
        hops: list[Hop] = []
        current = url
        while True:
            target = validate_url(current, self._policy)
            ips = await resolve_and_check(target, self._resolver, self._policy)
            ip = ips[0]
            resp = await self._send(method, target, ip, timeout)
            try:
                self._raise_if_proxy_denied(resp)
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
                return FetchResult(
                    status=resp.status_code,
                    final_url=target.url,
                    redirect_chain=tuple(hops),
                    headers=_subset(resp),
                    body=body,
                    resolved_ip=ip.compressed,
                )
            finally:
                await resp.aclose()

    def _raise_if_proxy_denied(self, resp: httpx.Response) -> None:
        """In proxy mode a plain-HTTP denial is a 403 carrying the guard's reason."""
        if self._proxy is None or resp.status_code != 403:
            return
        raw = resp.headers.get("x-falcon-block-reason")
        if raw is None:
            return
        try:
            reason = BlockReason(raw.strip())
        except ValueError:
            reason = BlockReason.EGRESS_DENIED
        raise SSRFBlocked(reason, "egress proxy")

    async def _send(
        self,
        method: str,
        target: CanonicalTarget,
        ip: IPAddress,
        timeout: float,
        content: bytes | None = None,
        content_type: str | None = None,
    ) -> httpx.Response:
        headers = {
            "Host": target.host_header,
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        extensions: dict[str, typing.Any] = {"timeout": httpx.Timeout(timeout).as_dict()}
        if self._proxy is None:
            req_url = target.url_for_ip(ip)  # pinned: httpx never resolves
            if target.scheme == "https":
                extensions["sni_hostname"] = target.host
        else:
            req_url = target.url  # the egress proxy re-resolves, re-checks and pins
        request = httpx.Request(method, req_url, headers=headers, content=content, extensions=extensions)
        token = _DIAL_HOST.set(target.host)
        try:
            # Straight to the transport: this skips httpx.AsyncClient's redirect
            # logic (which raises InvalidURL on a malformed Location) and cookies.
            return await self._transport.handle_async_request(request)
        finally:
            _DIAL_HOST.reset(token)


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
