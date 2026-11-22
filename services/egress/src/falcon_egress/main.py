"""Minimal asyncio HTTP CONNECT proxy (stub). Proxy on :3128, health/metrics on :8081."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from datetime import UTC, datetime

from falcon_egress import guard

PROXY_PORT = int(os.environ.get("EGRESS_PROXY_PORT", "3128"))
HEALTH_PORT = int(os.environ.get("EGRESS_HEALTH_PORT", "8081"))
MAX_HEADER_BYTES = 8192
IDLE_TIMEOUT = 120

log = logging.getLogger("falcon.egress")
COUNTERS = {"allowed": 0, "denied": 0}


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


async def _reply(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode())
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()


async def handle_proxy(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError, OSError):
        writer.close()
        return
    if len(head) > MAX_HEADER_BYTES:
        await _reply(writer, "431 Request Header Fields Too Large")
        return
    parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
    if len(parts) != 3 or parts[0].upper() != "CONNECT":
        await _reply(writer, "405 Method Not Allowed")  # CONNECT only
        return
    host, _, port_s = parts[1].rpartition(":")
    host = host.strip("[]")
    if not host or not port_s.isdigit():
        await _reply(writer, "400 Bad Request")
        return
    port = int(port_s)

    decision = await guard.check(host, port)
    if not decision.allowed:
        COUNTERS["denied"] += 1
        _log(logging.WARNING, "connect denied", host=host, port=port, reason=decision.reason)
        await _reply(writer, "403 Forbidden")
        return
    try:
        up_reader, up_writer = await asyncio.wait_for(
            asyncio.open_connection(decision.addresses[0], port), 10
        )
    except (OSError, TimeoutError):
        COUNTERS["denied"] += 1
        await _reply(writer, "502 Bad Gateway")
        return
    COUNTERS["allowed"] += 1
    _log(logging.INFO, "connect allowed", host=host, port=port)
    writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await writer.drain()
    await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))


def _metrics() -> bytes:
    lines = ["# TYPE fl_egress_connects_total counter"]
    lines += [f'fl_egress_connects_total{{result="{k}"}} {v}' for k, v in COUNTERS.items()]
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
    proxy = await asyncio.start_server(handle_proxy, "0.0.0.0", PROXY_PORT)
    health = await asyncio.start_server(handle_health, "0.0.0.0", HEALTH_PORT)
    _log(logging.INFO, "egress proxy started", proxy_port=PROXY_PORT, health_port=HEALTH_PORT)
    async with proxy, health:
        await asyncio.gather(proxy.serve_forever(), health.serve_forever())


def main() -> None:
    asyncio.run(serve())


if __name__ == "__main__":
    main()
