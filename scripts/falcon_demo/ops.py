"""urls, prewarm, tunnel and tunnel-stop helpers behind `make demo`, `make urls`, `make tunnel`."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from urllib.parse import quote

import httpx

from .common import PRIVATE_DIR, ApiClient, Endpoints, load_env

TUNNEL_URL_FILE = PRIVATE_DIR / "tunnel_url.txt"
TUNNEL_PID_FILE = PRIVATE_DIR / "tunnel.pid"
TUNNEL_LOG_FILE = PRIVATE_DIR / "tunnel.log"
TRYCLOUDFLARE_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def url_table(env: Mapping[str, str]) -> list[tuple[str, str]]:
    ep = Endpoints.from_env(env)
    rows = [
        ("Web app", ep.gateway + "/"),
        ("Incident board", ep.gateway + "/board"),
        ("Incidents", ep.gateway + "/incidents"),
        ("API docs", ep.gateway + "/v1/docs"),
        ("MCP endpoint", ep.gateway + "/mcp"),
    ]
    names = (
        "Command overview",
        "Detection quality",
        "Pipeline performance",
        "Signals and feeds",
        "LLM and cost",
        "Sentinel",
    )
    rows += [(f"Grafana {i}: {n}", f"{ep.grafana}/dashboards?query={quote(n)}") for i, n in enumerate(names, 1)]
    phoenix = ep.phoenix if env.get("FL_PHOENIX_PORT") else "internal only (set FL_PHOENIX_PORT once published)"
    rows += [("Prometheus", ep.prometheus), ("Phoenix (LLM traces)", phoenix)]
    return rows


def print_urls(env: Mapping[str, str], out: Callable[[str], None] = print) -> None:
    out("\nOpen these (local CA: accept the certificate warning once):")
    for name, u in url_table(env):
        out(f"  {name:<34} {u}")
    if TUNNEL_URL_FILE.is_file():
        out(f"  {'Public tunnel (last run)':<34} {TUNNEL_URL_FILE.read_text().strip()}")


def next_commands(out: Callable[[str], None] = print) -> None:
    out("\nNext:")
    out("  make replay RATE=2/s DURATION=10m   live traffic + planted campaign (an incident fires mid-run)")
    out("  make tunnel                         public URL for judges (make tunnel-stop to close it)")
    out("  make demo-reset                     back to a clean seeded state")


def _ollama_host_url(env: Mapping[str, str]) -> str:
    base = env.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    return base.replace("host.docker.internal", "localhost")


def prewarm(env: Mapping[str, str], out: Callable[[str], None] = print) -> dict[str, bool]:
    """Warm the local model and the sandbox browser pool. Each step degrades to a message, never an error."""
    res: dict[str, bool] = {}
    model = env.get("FL_LOCAL_MODEL") or "inkling-2-mini-chat"
    try:
        r = httpx.post(
            _ollama_host_url(env) + "/api/generate",
            json={"model": model, "prompt": "", "keep_alive": "30m", "stream": False},
            timeout=120.0,
        )
        res["ollama"] = r.status_code == 200
        out(
            f"prewarm: ollama {model}: "
            + ("loaded" if res["ollama"] else f"HTTP {r.status_code} (model missing? see infra/ollama/README.md)")
        )
    except httpx.HTTPError:
        res["ollama"] = False
        out(f"prewarm: ollama not reachable at {_ollama_host_url(env)}; local-model scenes will be cold or degraded")
    ep = Endpoints.from_env(env)
    client = ApiClient(ep.gateway, env.get("FL_SANDBOX_API_KEY"))
    try:
        if not client.healthy():
            res["sandbox"] = False
            out("prewarm: API not reachable; sandbox pool not warmed")
        else:
            # One fixture check per profile warms the browser pool (a fixture page, never a live site).
            for u in ("https://falcon-demo-bank.test/", "https://falcon-demo-bank-secure-pay.test/"):
                client.check_url(u, idem=f"prewarm-{u}", wait=8)
            res["sandbox"] = True
            out("prewarm: sandbox pool warmed with two fixture checks")
    except Exception as exc:  # noqa: BLE001 - prewarm must never block the demo
        res["sandbox"] = False
        out(f"prewarm: sandbox warm-up skipped ({exc})")
    finally:
        client.close()
    return res


# --- tunnel ----------------------------------------------------------------------------------------------------


def tunnel_command(env: Mapping[str, str]) -> list[str]:
    port = env.get("FL_GATEWAY_PORT") or "8443"
    # Caddy serves only the `localhost` site, so the Host header and SNI must be rewritten (L1-verified).
    return [
        "cloudflared", "tunnel", "--no-autoupdate",
        "--url", f"https://localhost:{port}",
        "--no-tls-verify",
        "--http-host-header", "localhost",
        "--origin-server-name", "localhost",
    ]  # fmt: skip


def parse_tunnel_url(text: str) -> str | None:
    m = TRYCLOUDFLARE_RE.search(text)
    return m.group(0) if m else None


def verify_tunnel(url: str, *, attempts: int = 20, sleep: Callable[[float], None] = time.sleep) -> bool:
    """The quick tunnel needs a few seconds before DNS resolves; require JSON from /v1/version."""
    for _ in range(attempts):
        try:
            r = httpx.get(url + "/v1/version", timeout=8.0)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                return True
        except httpx.HTTPError:
            pass
        sleep(3)
    return False


def _qr(url: str, out: Callable[[str], None]) -> None:
    if shutil.which("qrencode"):
        out(subprocess.run(["qrencode", "-t", "ANSIUTF8", url], capture_output=True, text=True, check=False).stdout)  # noqa: S603, S607
    else:
        out("(install `qrencode` with brew for a terminal QR code)")


def _saved_url() -> str:
    return TUNNEL_URL_FILE.read_text().strip() if TUNNEL_URL_FILE.is_file() else "?"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def tunnel_start(env: Mapping[str, str], out: Callable[[str], None] = print, wait_s: float = 45.0) -> int:
    if shutil.which("cloudflared") is None:
        out("tunnel: cloudflared not found. Install it with `brew install cloudflared`.")
        return 1
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    if TUNNEL_PID_FILE.is_file():
        pid = int(TUNNEL_PID_FILE.read_text().strip() or 0)
        if pid and _pid_alive(pid):
            out(f"tunnel: already running (pid {pid}) at {_saved_url()}")
            return 0
    TUNNEL_LOG_FILE.write_text("")
    with TUNNEL_LOG_FILE.open("ab") as log:
        proc = subprocess.Popen(  # noqa: S603
            tunnel_command(env), stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True
        )
    TUNNEL_PID_FILE.write_text(str(proc.pid))
    deadline = time.monotonic() + wait_s
    url: str | None = None
    while time.monotonic() < deadline and url is None:
        if proc.poll() is not None:
            out(f"tunnel: cloudflared exited early; see {TUNNEL_LOG_FILE}")
            TUNNEL_PID_FILE.unlink(missing_ok=True)
            return 1
        url = parse_tunnel_url(TUNNEL_LOG_FILE.read_text(errors="replace"))
        time.sleep(1)
    if url is None:
        out(f"tunnel: no URL after {wait_s:.0f}s; see {TUNNEL_LOG_FILE}")
        return 1
    if not verify_tunnel(url):
        out(f"tunnel: {url} did not return JSON from /v1/version. Is the stack up (make up)? Not publishing the URL.")
        return 1
    TUNNEL_URL_FILE.write_text(url + "\n")
    out(f"\nPublic URL: {url}")
    out("(saved to data/private/tunnel_url.txt; stop with `make tunnel-stop`; keep the Mac awake: caffeinate -d)")
    out(
        "Allow the origin in the app: set FL_PUBLIC_BASE_URL="
        + url
        + " in .env, then `docker compose up -d api web` (CORS follows it)."
    )
    _qr(url, out)
    return 0


def tunnel_stop(out: Callable[[str], None] = print) -> int:
    """Stops only the cloudflared we started (pid file); other tunnels are left alone."""
    if not TUNNEL_PID_FILE.is_file():
        out("tunnel-stop: no tunnel started by `make tunnel` (other cloudflared processes are not touched).")
        return 0
    pid = int(TUNNEL_PID_FILE.read_text().strip() or 0)
    if pid and _pid_alive(pid):
        os.kill(pid, signal.SIGTERM)
        out(f"tunnel-stop: stopped cloudflared pid {pid}")
    TUNNEL_PID_FILE.unlink(missing_ok=True)
    TUNNEL_URL_FILE.unlink(missing_ok=True)
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    env = load_env()
    if cmd == "urls":
        print_urls(env)
        return 0
    if cmd == "next":
        next_commands()
        return 0
    if cmd == "prewarm":
        prewarm(env)
        return 0
    if cmd == "reset-state":
        (PRIVATE_DIR / "seed_state.json").unlink(missing_ok=True)
        print("seed state cleared")
        return 0
    if cmd == "tunnel":
        return tunnel_start(env)
    if cmd == "tunnel-stop":
        return tunnel_stop()
    print("usage: python -m falcon_demo.ops urls|next|prewarm|tunnel|tunnel-stop", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
