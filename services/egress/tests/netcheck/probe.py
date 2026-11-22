"""Runs inside the sandbox-network probe container. It uses only the stdlib, and the
exit code is the result.

Required:
  1. Through the proxy, http://169.254.169.254/ returns 403 (absolute-form plain HTTP).
  2. CONNECT 169.254.169.254:80 through the proxy returns 403.
  3. CONNECT 127.0.0.1:443 and CONNECT redis:6379 return 403.
  4. A direct connection to 1.1.1.1:80 (no proxy) fails, because there is no route.
Informational (needs internet on the host):
  5. Through the proxy, http://example.com/ returns 200.
"""

from __future__ import annotations

import socket
import sys
import urllib.error
import urllib.request

PROXY = ("egress-proxy", 3128)
failures: list[str] = []


def raw(req: bytes) -> bytes:
    with socket.create_connection(PROXY, timeout=10) as s:
        s.sendall(req)
        return s.recv(4096)


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
    if not ok:
        failures.append(name)


opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({"http": "http://egress-proxy:3128"})
)
try:
    opener.open("http://169.254.169.254/latest/meta-data/", timeout=10)
    check("proxy http metadata", False, "got a response")
except urllib.error.HTTPError as e:
    check(
        "proxy http metadata", e.code == 403, f"{e.code} {e.headers.get('X-Falcon-Block-Reason')}"
    )

for target in (b"169.254.169.254:80", b"127.0.0.1:443", b"redis:6379"):
    resp = raw(b"CONNECT " + target + b" HTTP/1.1\r\n\r\n")
    line = resp.split(b"\r\n", 1)[0].decode()
    check(f"proxy CONNECT {target.decode()}", " 403 " in line + " ", line)

try:
    socket.create_connection(("1.1.1.1", 80), timeout=5).close()
    check("direct 1.1.1.1 no route", False, "connected")
except OSError as e:
    check("direct 1.1.1.1 no route", True, f"{type(e).__name__}: {e}")

try:
    r = opener.open("http://example.com/", timeout=15)
    print(f"INFO proxy http example.com: {r.status}", flush=True)
except Exception as e:  # noqa: BLE001 - informational only
    print(f"INFO proxy http example.com: {type(e).__name__}: {e}", flush=True)

sys.exit(1 if failures else 0)
