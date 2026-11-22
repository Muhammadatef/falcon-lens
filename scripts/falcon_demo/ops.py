"""urls, prewarm, tunnel and tunnel-stop helpers behind `make demo`, `make urls`, `make tunnel`.

What it does:
    `urls` prints the local service URLs; `next` prints suggested follow-up commands; `prewarm` loads the
    local model in Ollama and runs two fixture checks to warm the sandbox browser pool; `tunnel` starts a
    cloudflared quick tunnel to the gateway; `tunnel-stop` stops it; `reset` deletes the demo Docker volumes
    and seed state; `reset-state` only deletes the seed state file.

When to use it:
    `make demo` runs prewarm, urls and next for you. Use `make tunnel` to share the demo with a phone or
    judge, and `make demo-reset` to return to a clean slate before a rehearsal.

How to run:
    make urls | make tunnel | make tunnel-stop | make demo-reset [YES=1]
    PYTHONPATH=scripts uv run python -m falcon_demo prewarm     (also: next, reset-state)

Inputs:
    .env and env vars (FL_GATEWAY_PORT, OLLAMA_BASE_URL, FL_LOCAL_MODEL, FL_SANDBOX_API_KEY, YES), the
    `cloudflared` binary for tunnels and `docker compose` for reset.

Outputs / side effects:
    tunnel writes data/private/tunnel_url.txt, tunnel.pid and tunnel.log, starts a background cloudflared
    process, and checks that /v1/version answers JSON before saving the URL. reset runs
    `docker compose down`, then `docker volume rm` on the Postgres and Redis volumes (names read from
    `docker compose config`), then deletes data/private/seed_state.json. prewarm calls Ollama and the local
    API only.

Safety notes:
    reset is destructive: it asks you to type the project name unless YES=1 is set. A tunnel makes your
    local gateway reachable from the internet; stop it when done. Files under data/private/ are
    gitignored; never commit them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import quote

import httpx

from .common import PRIVATE_DIR, REPO_ROOT, ApiClient, Endpoints, load_env

TUNNEL_URL_FILE = PRIVATE_DIR / "tunnel_url.txt"
TUNNEL_PID_FILE = PRIVATE_DIR / "tunnel.pid"
TUNNEL_LOG_FILE = PRIVATE_DIR / "tunnel.log"
TRYCLOUDFLARE_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def url_table(env: Mapping[str, str]) -> list[tuple[str, str]]:
    """Rows of (label, URL) for the services of the local stack."""
    ep = Endpoints.from_env(env)
    rows = [
        ("Web app", ep.gateway + "/"),
        # Routes the web app serves (web/app/campaigns, web/app/ops). Keep in step with docs/DEMO.md.
        ("Campaign board", ep.gateway + "/campaigns"),
        ("Operator incident board", ep.gateway + "/ops"),
        ("MCP endpoint", ep.gateway + "/mcp"),
    ]
    names = (
        "Command overview",
        "Detection quality",
        "Pipeline performance",
        "AI operations",
        "Security",
        "Sentinel",
    )
    rows += [(f"Grafana {i}: {n}", f"{ep.grafana}/dashboards?query={quote(n)}") for i, n in enumerate(names, 1)]
    phoenix = ep.phoenix if env.get("FL_PHOENIX_PORT") else "internal only (set FL_PHOENIX_PORT once published)"
    rows += [("Prometheus", ep.prometheus), ("Phoenix (LLM traces)", phoenix)]
    return rows


def print_urls(env: Mapping[str, str], out: Callable[[str], None] = print) -> None:
    """Print the local URLs table."""
    out("\nOpen these (local CA: accept the certificate warning once):")
    for name, u in url_table(env):
        out(f"  {name:<34} {u}")
    if TUNNEL_URL_FILE.is_file():
        out(f"  {'Public tunnel (last run)':<34} {TUNNEL_URL_FILE.read_text().strip()}")


def next_commands(out: Callable[[str], None] = print) -> None:
    """Print the suggested commands to run after `make demo`."""
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
    """The cloudflared command line for a quick tunnel to the local gateway."""
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
    """Find the trycloudflare.com URL in cloudflared's log text, or None."""
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
    """Start a cloudflared quick tunnel, verify it, save the URL under data/private; 0 on success."""
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


def _pid_is_cloudflared(pid: int) -> bool:
    r = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    return "cloudflared" in r.stdout


def _read_pid(path: Path) -> int | None:
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid > 1 else None


def tunnel_stop(out: Callable[[str], None] = print) -> int:
    """Stops only the cloudflared we started (pid file, command verified); other tunnels are left alone."""
    if not TUNNEL_PID_FILE.is_file():
        out("tunnel-stop: no tunnel started by `make tunnel` (other cloudflared processes are not touched).")
        return 0
    pid = _read_pid(TUNNEL_PID_FILE)
    if pid is None:
        out("tunnel-stop: pid file is garbled; removed it, nothing killed.")
    elif _pid_alive(pid) and _pid_is_cloudflared(pid):
        os.kill(pid, signal.SIGTERM)
        out(f"tunnel-stop: stopped cloudflared pid {pid}")
    else:
        out(f"tunnel-stop: pid {pid} is not a running cloudflared; nothing killed.")
    TUNNEL_PID_FILE.unlink(missing_ok=True)
    TUNNEL_URL_FILE.unlink(missing_ok=True)
    return 0


# --- demo-reset ------------------------------------------------------------------------------------------------
RESET_VOLUMES = ("pg_data", "redis_data")


def reset_plan(config: dict[str, object]) -> tuple[str, list[str]]:
    """(project name, volume names) from `docker compose config --format json`, never guessed."""
    name = config.get("name")
    vols = config.get("volumes")
    if not isinstance(name, str) or not name or not isinstance(vols, dict):
        raise ValueError("compose config has no project name or volumes")
    out = []
    for key in RESET_VOLUMES:
        v = vols.get(key)
        vname = v.get("name") if isinstance(v, dict) else None
        if not isinstance(vname, str) or not vname:
            raise ValueError(f"volume '{key}' not found in compose config")
        out.append(vname)
    return name, out


def compose_config() -> dict[str, object]:
    """`docker compose config` as parsed JSON (used to resolve project and volume names)."""
    r = subprocess.run(
        ["docker", "compose", "--profile", "core", "--profile", "obs", "--profile", "tools"]
        + ["config", "--format", "json"],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )  # fmt: skip
    if r.returncode != 0:
        raise ValueError("`docker compose config` failed: " + r.stderr.strip().splitlines()[-1:][0] if r.stderr else "")
    doc = json.loads(r.stdout)
    if not isinstance(doc, dict):
        raise ValueError("unexpected compose config")
    return doc


def demo_reset(assume_yes: bool, out: Callable[[str], None] = print, ask: Callable[[str], str] = input) -> int:
    """Stop the stack and delete the Postgres and Redis volumes and the seed state (asks first)."""
    try:
        project, volumes = reset_plan(compose_config())
    except (ValueError, OSError) as exc:
        out(f"demo-reset: cannot resolve project/volumes ({exc}); nothing deleted.")
        return 1
    out(f"demo-reset: project '{project}', volumes to delete: {', '.join(volumes)}")
    if not assume_yes and ask("Type the project name to confirm: ").strip() != project:
        out("aborted")
        return 1
    base = ["docker", "compose", "--profile", "core", "--profile", "obs", "--profile", "tools", "--profile", "stretch"]
    subprocess.run([*base, "down", "--remove-orphans"], cwd=REPO_ROOT, check=True)
    subprocess.run(["docker", "volume", "rm", "-f", *volumes], check=True)
    (PRIVATE_DIR / "seed_state.json").unlink(missing_ok=True)
    out("demo-reset: volumes and seed state removed")
    return 0


def main(argv: list[str]) -> int:
    """Run one ops command (urls, next, prewarm, tunnel, tunnel-stop, reset, reset-state)."""
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
    if cmd == "reset":
        return demo_reset(assume_yes=os.environ.get("YES") == "1")
    if cmd == "reset-state":
        (PRIVATE_DIR / "seed_state.json").unlink(missing_ok=True)
        print("seed state cleared")
        return 0
    if cmd == "tunnel":
        return tunnel_start(env)
    if cmd == "tunnel-stop":
        return tunnel_stop()
    print("usage: python -m falcon_demo.ops urls|next|prewarm|tunnel|tunnel-stop|reset|reset-state", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
