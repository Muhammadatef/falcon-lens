"""Filtering egress proxy. Proxy on :3128, health and metrics on :8081.

It supports two request forms, and both go through the shared SSRF guard
(``falcon_core.security``):

* ``CONNECT host:port``: used for https. The proxy resolves the name itself, checks
  every address, then dials the checked IP (pinned), never the name.
* ``GET|HEAD http://host/path``: absolute-form plain HTTP, which Chromium sends for
  http pages when ``HTTP_PROXY`` is set. It goes through ``validate_url`` and
  ``resolve_and_check``, then the proxy dials the checked IP and forwards one
  origin-form request with ``Connection: close``.

Everything else is refused: origin-form requests, absolute-form https, other
methods for plain HTTP (the sandbox never submits), and request bodies. A denial
is a ``403`` with ``X-Falcon-Block-Reason: <BlockReason>`` and increments
``fl_ssrf_blocked_total{reason}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from falcon_core.security import GuardPolicy, Resolver
from falcon_egress import guard

PROXY_PORT = int(os.environ.get("EGRESS_PROXY_PORT", "3128"))
HEALTH_PORT = int(os.environ.get("EGRESS_HEALTH_PORT", "8081"))
MAX_HEADER_BYTES = 8192
HEAD_TIMEOUT = 10
DIAL_TIMEOUT = 10
IDLE_TIMEOUT = 120

log = logging.getLogger("falcon.egress")
COUNTERS = {"allowed": 0, "denied": 0}
BLOCKED: dict[str, int] = {}

SAFE_METHODS = frozenset({"GET", "HEAD"})
# Never forwarded upstream: hop-by-hop headers (RFC 9110 §7.6.1), proxy credentials,
# and Host (rebuilt from the checked URL so it cannot disagree with what was checked).
_DROP_HEADERS = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-connection",
        b"proxy-authorization",
        b"proxy-authenticate",
        b"te",
        b"trailer",
        b"transfer-encoding",
        b"upgrade",
        b"host",
    }
)

OpenConnection = Callable[[str, int], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


def _log(level: int, msg: str, **fields: object) -> None:
    rec = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "level": logging.getLevelName(level).lower(),
        "service": "egress",
        "msg": msg,
        **fields,
    }
    print(json.dumps(rec), file=sys.stdout, flush=True)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await asyncio.wait_for(reader.read(65536), IDLE_TIMEOUT):
            writer.write(data)
            await writer.drain()
    except (OSError, TimeoutError):
        pass
    finally:
        with contextlib.suppress(OSError):
            writer.close()


async def _reply(writer: asyncio.StreamWriter, status: str, extra: str = "") -> None:
    writer.write(
        f"HTTP/1.1 {status}\r\n{extra}Connection: close\r\nContent-Length: 0\r\n\r\n".encode()
    )
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()


async def _deny(writer: asyncio.StreamWriter, reason: str, **fields: object) -> None:
    COUNTERS["denied"] += 1
    BLOCKED[reason] = BLOCKED.get(reason, 0) + 1
    _log(logging.WARNING, "egress denied", reason=reason, **fields)
    await _reply(writer, "403 Forbidden", f"X-Falcon-Block-Reason: {reason}\r\n")


async def _default_open(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_connection(host, port)


def _valid_header_line(line: bytes) -> bool:
    # No obs-fold, no bare CR/LF/NUL (request smuggling and header injection).
    return (
        b":" in line
        and not line[:1].isspace()
        and not any(c in line for c in (b"\r", b"\n", b"\0"))
        and line.split(b":", 1)[0].strip() == line.split(b":", 1)[0]
        and bool(line.split(b":", 1)[0])
    )


def make_proxy_handler(
    *,
    resolver: Resolver | None = None,
    policy: GuardPolicy | None = None,
    open_connection: OpenConnection = _default_open,
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    """Build the proxy connection handler. Tests inject ``resolver`` and
    ``open_connection``; production uses the OS resolver and real sockets."""
    pol = policy or guard.policy_from_env()

    async def dial(host: str, port: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        return await asyncio.wait_for(open_connection(host, port), DIAL_TIMEOUT)

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEAD_TIMEOUT)
        except asyncio.LimitOverrunError:
            await _reply(writer, "431 Request Header Fields Too Large")
            return
        except (asyncio.IncompleteReadError, TimeoutError, OSError):
            writer.close()
            return
        if len(head) > MAX_HEADER_BYTES:
            await _reply(writer, "431 Request Header Fields Too Large")
            return
        lines = head[:-4].split(b"\r\n")
        parts = lines[0].decode("latin-1").split(" ")
        header_lines = lines[1:]
        if (
            len(parts) != 3
            or parts[2] not in ("HTTP/1.1", "HTTP/1.0")
            or not all(_valid_header_line(h) for h in header_lines)
        ):
            await _reply(writer, "400 Bad Request")
            return
        method, target = parts[0].upper(), parts[1]

        if method == "CONNECT":
            await _connect(reader, writer, target)
        elif target[:7].lower() == "http://":
            await _forward(writer, method, target, header_lines)
        elif target[:8].lower() == "https://":
            await _deny(writer, "scheme", target="absolute-form https")
        else:
            await _reply(writer, "400 Bad Request")  # origin-form: not a proxy request

    async def _connect(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter, target: str
    ) -> None:
        host, _, port_s = target.rpartition(":")
        if not host or not port_s.isdigit():
            await _reply(writer, "400 Bad Request")
            return
        port = int(port_s)
        decision = await guard.check(host, port, resolver=resolver, policy=pol)
        if not decision.allowed:
            await _deny(writer, decision.reason, host=host, port=port, mode="connect")
            return
        ip = decision.addresses[0]
        try:
            up_reader, up_writer = await dial(ip, port)  # pinned: the checked IP
        except (OSError, TimeoutError):
            COUNTERS["denied"] += 1
            await _reply(writer, "502 Bad Gateway")
            return
        COUNTERS["allowed"] += 1
        _log(logging.INFO, "connect allowed", host=host, port=port, ip=ip)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    async def _forward(
        writer: asyncio.StreamWriter, method: str, url: str, header_lines: list[bytes]
    ) -> None:
        if method not in SAFE_METHODS:
            COUNTERS["denied"] += 1
            BLOCKED["method_not_allowed"] = BLOCKED.get("method_not_allowed", 0) + 1
            _log(logging.WARNING, "egress denied", reason="method_not_allowed", method=method)
            await _reply(writer, "405 Method Not Allowed", "Allow: GET, HEAD\r\n")
            return
        kept: list[bytes] = []
        for line in header_lines:
            name, _, value = line.partition(b":")
            lname = name.strip().lower()
            if lname == b"content-length" and value.strip() not in (b"", b"0"):
                await _reply(writer, "400 Bad Request")  # no request bodies
                return
            if lname == b"transfer-encoding":
                await _reply(writer, "400 Bad Request")
                return
            if lname not in _DROP_HEADERS:
                kept.append(line)
        decision = await guard.check_url(url, resolver=resolver, policy=pol)
        if not decision.allowed:
            await _deny(writer, decision.reason, mode="http")
            return
        ip = decision.addresses[0]
        try:
            up_reader, up_writer = await dial(ip, decision.port)  # pinned
        except (OSError, TimeoutError):
            COUNTERS["denied"] += 1
            await _reply(writer, "502 Bad Gateway")
            return
        COUNTERS["allowed"] += 1
        _log(logging.INFO, "http allowed", host=decision.host_header, ip=ip)
        out = (
            f"{method} {decision.request_target} HTTP/1.1\r\n"
            f"Host: {decision.host_header}\r\n".encode("ascii")
            + b"".join(line + b"\r\n" for line in kept)
            + b"Connection: close\r\n\r\n"
        )
        up_writer.write(out)
        await up_writer.drain()
        # One request per client connection: only relay the response back.
        await _pipe(up_reader, writer)
        with contextlib.suppress(OSError):
            up_writer.close()

    return handle


handle_proxy = make_proxy_handler()


def _metrics() -> bytes:
    lines = ["# TYPE fl_egress_connects_total counter"]
    lines += [f'fl_egress_connects_total{{result="{k}"}} {v}' for k, v in COUNTERS.items()]
    lines.append("# TYPE fl_ssrf_blocked_total counter")
    lines += [f'fl_ssrf_blocked_total{{reason="{k}"}} {v}' for k, v in sorted(BLOCKED.items())]
    return ("\n".join(lines) + "\n").encode()


async def handle_health(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError):
        writer.close()
        return
    path = head.split(b"\r\n", 1)[0].decode("latin-1").split()[1:2]
    target = path[0] if path else ""
    if target in ("/healthz", "/readyz"):
        body, ctype, status = b'{"status":"ok","service":"egress"}', "application/json", "200 OK"
    elif target == "/metrics":
        body, ctype, status = _metrics(), "text/plain; version=0.0.4", "200 OK"
    else:
        body, ctype, status = b"not found", "text/plain", "404 Not Found"
    writer.write(
        f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\nContent-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n".encode()
        + body
    )
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()


async def serve() -> None:
    proxy = await asyncio.start_server(
        make_proxy_handler(), "0.0.0.0", PROXY_PORT, limit=MAX_HEADER_BYTES * 2
    )
    health = await asyncio.start_server(handle_health, "0.0.0.0", HEALTH_PORT)
    _log(logging.INFO, "egress proxy started", proxy_port=PROXY_PORT, health_port=HEALTH_PORT)
    async with proxy, health:
        await asyncio.gather(proxy.serve_forever(), health.serve_forever())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
