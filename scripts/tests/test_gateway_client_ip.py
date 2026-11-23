# ruff: noqa: S603, S607
"""Real Caddy (docker) in front of an echo upstream: the real Caddyfile's global block and /v1
handle must hand the API one distinct client IP per Cf-Connecting-Ip and overwrite a client-sent
X-Falcon-Client-IP. Skipped when docker or the image is unavailable."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "caddy:2.11.9-alpine"


def _docker_ok() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="docker / caddy image not available")


class _Echo(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"ip": self.headers.get("X-Falcon-Client-IP")}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a: object) -> None:
        return


def _derived_caddyfile(upstream: str) -> str:
    src = (ROOT / "infra/gateway/Caddyfile").read_text()
    glob = src[: src.index("# Internal plain-HTTP")]
    m = re.search(r"\thandle /v1/\* \{.*?\n\t\}\n", src, re.S)
    assert m
    handle = m.group(0).replace("api:8000", upstream)
    return f"{glob}\nhttp://:8080 {{\n{handle}}}\n"


def test_gateway_sets_client_ip_header(tmp_path: Path) -> None:
    srv = HTTPServer(("0.0.0.0", 0), _Echo)  # noqa: S104
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    (tmp_path / "Caddyfile").write_text(_derived_caddyfile(f"host.docker.internal:{srv.server_port}"))
    name = f"fl-gw-test-{srv.server_port}"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-p",
            "127.0.0.1::8080",
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{tmp_path}/Caddyfile:/etc/caddy/Caddyfile:ro",
            IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        out = subprocess.run(["docker", "port", name, "8080"], check=True, capture_output=True, text=True)
        port = out.stdout.splitlines()[0].split(":")[-1].strip()

        def get(headers: dict[str, str]) -> str | None:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/x", headers=headers)
            for _ in range(30):
                try:
                    with urllib.request.urlopen(req, timeout=3) as r:  # noqa: S310
                        return json.load(r)["ip"]  # type: ignore[no-any-return]
                except OSError:
                    time.sleep(0.3)
            raise AssertionError("gateway did not answer")

        a = get({"Cf-Connecting-Ip": "203.0.113.9"})
        b = get({"Cf-Connecting-Ip": "198.51.100.7"})
        assert (a, b) == ("203.0.113.9", "198.51.100.7")
        assert get({"Cf-Connecting-Ip": "203.0.113.9", "X-Falcon-Client-IP": "6.6.6.6"}) == "203.0.113.9"
        assert get({"X-Falcon-Client-IP": "6.6.6.6"}) != "6.6.6.6"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        srv.shutdown()
