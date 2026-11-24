"""Demo-day control: readiness board, pause/resume of competing load, pre-warm and voice rehearsal.

What it does:
    `check`     read-only READY / NOT READY board (stack health, memory, swap, CPU, thermal, disk, other
                compose projects, LLM gate, native STT, tunnel, timed link + message probe). Exit 0 only if READY.
    `on`        prints exactly what it would pause; acts only with --yes (or CONFIRM=yes). Docker projects get
                `docker compose -p <proj> stop`; listed processes get SIGSTOP. State goes to work/demo_mode/state.json.
                Then pre-warms STT, the check path and the voice web route, and runs `check`.
    `off`       restores exactly what state.json lists (`docker compose -p <proj> start`, SIGCONT). Idempotent.
    `rehearsal` speaks the owner's demo lines with macOS `say`, POSTs them to /v1/voice/utterance (skipped with
                a message if the endpoint is not merged), then puts 3 demo messages on the clipboard.

Never: touches the `falcon` project except read-only checks, runs down/rm/prune, or kills a process.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "infra" / "demo_mode.yaml"
STATE = REPO / "work" / "demo_mode" / "state.json"


def data_root() -> Path:
    """data/private lives only in the main checkout: FL_REPO_ROOT, else ~/Eaglelens, else this repo."""
    env = os.environ.get("FL_REPO_ROOT")
    for cand in (Path(env) if env else None, Path.home() / "Eaglelens", REPO):
        if cand is not None and (cand / "data" / "private").is_dir():
            return cand
    return REPO


TUNNEL_FILE = data_root() / "data" / "private" / "tunnel_url.txt"
KIT_MESSAGES = Path.home() / "Eaglelens" / "demo-kit" / "messages"
STT_URL = "http://127.0.0.1:8093"
OLLAMA_URL = "http://127.0.0.1:11434"
FALCON = "falcon"

MIN_FREE_MEM_PCT = 25.0  # below this macOS compresses/swaps and Whisper + LLM latency spikes
MAX_SWAP_MB = 2048.0  # heavy swap makes first-token latency unpredictable on stage
MIN_CPU_IDLE_PCT = 50.0  # the cascade + STT need headroom; a busy CPU adds seconds
MIN_DISK_FREE_GB = 15.0  # Docker, Ollama and Postgres fail badly on a full disk
MAX_LINK_MS = 8000.0  # one link check must land inside the API's 8 s wait cap
MAX_MESSAGE_MS = 8000.0  # same for a message check

READY, NOT_READY = "READY", "NOT READY"
Runner = Callable[[list[str]], str]
PS_CMD = ["ps", "-axo", "pid=,rss=,command="]


def sh(cmd: list[str], timeout: float = 20.0) -> str:
    """Run a read-only command; returns stdout, or '' if it is missing, fails or times out."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout


def run_rc(cmd: list[str], timeout: float = 120.0) -> int:
    """Run a state-changing command (stop/start only); returns its exit code, 127 if missing, 124 on timeout."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False).returncode  # noqa: S603
    except OSError:
        return 127
    except subprocess.TimeoutExpired:
        return 124


@dataclass
class Row:
    """One line of the board: status is OK, WARN, FAIL or INFO. Only FAIL blocks READY."""

    name: str
    status: str
    detail: str
    why: str = ""


# ---------------------------------------------------------------- config and plan


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    """Read infra/demo_mode.yaml (missing file means: pause nothing but other compose projects)."""
    doc: dict[str, Any] = {}
    if path.is_file():
        doc = yaml.safe_load(path.read_text()) or {}
    return {
        "keep_projects": sorted({FALCON, *[str(x) for x in doc.get("keep_projects", [])]}),
        "pause_processes": [str(x) for x in doc.get("pause_processes", [])],
        "protect_processes": [str(x) for x in doc.get("protect_processes", [])],
    }


def parse_compose_ls(text: str) -> list[dict[str, Any]]:
    """`docker compose ls --format json` -> [{'name', 'running': int}] (count from 'running(N)')."""
    try:
        rows = json.loads(text) if text.strip() else []
    except json.JSONDecodeError:
        return []
    out = []
    for r in rows:
        m = re.search(r"running\((\d+)\)", str(r.get("Status", "")))
        out.append({"name": str(r.get("Name", "")), "running": int(m.group(1)) if m else 0})
    return out


def parse_ps(text: str) -> list[dict[str, Any]]:
    """`ps -axo pid=,rss=,command=` -> [{'pid', 'rss_kb', 'command'}]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)$", line)
        if m:
            out.append({"pid": int(m.group(1)), "rss_kb": int(m.group(2)), "command": m.group(3)})
    return out


@dataclass
class Plan:
    """What `on` would pause."""

    projects: list[str] = field(default_factory=list)
    processes: list[dict[str, Any]] = field(default_factory=list)  # pid, match, command

    def empty(self) -> bool:
        return not self.projects and not self.processes

    def lines(self) -> list[str]:
        out = [f"docker compose -p {p} stop" for p in self.projects]
        out += [f"SIGSTOP pid {p['pid']} ({p['match']}): {p['command'][:80]}" for p in self.processes]
        return out or ["nothing to pause"]


def build_plan(compose_ls: str, ps: str, cfg: dict[str, Any], own: set[int] | None = None) -> Plan:
    """Pure: running compose projects other than the kept ones, plus listed, unprotected, non-own processes."""
    keep = {k.lower() for k in cfg["keep_projects"]} | {FALCON}
    running = [p["name"] for p in parse_compose_ls(compose_ls) if p["running"] > 0]
    plan = Plan(projects=sorted(n for n in running if n.lower() not in keep))
    protect = [p.lower() for p in cfg["protect_processes"]]
    for proc in parse_ps(ps):
        if proc["pid"] in (own or set()):
            continue
        cmd = proc["command"]
        low = cmd.lower()
        match = next((m for m in cfg["pause_processes"] if m.lower() in low), None)
        if match is None:
            continue
        if any(p in low and p not in match.lower() for p in protect):
            continue
        plan.processes.append({"pid": proc["pid"], "match": match, "command": cmd})
    return plan


def own_pids() -> set[int]:
    """This process and its parent chain (never pause the shell running make)."""
    pids = {os.getpid()}
    pid = os.getppid()
    for _ in range(12):
        if pid <= 1 or pid in pids:
            break
        pids.add(pid)
        out = sh(["ps", "-o", "ppid=", "-p", str(pid)]).strip()
        pid = int(out) if out.isdigit() else 0
    return pids


# ---------------------------------------------------------------- state


def save_state(state: dict[str, Any], path: Path = STATE) -> None:
    """Atomic write of the paused-set."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def load_state(path: Path = STATE) -> dict[str, Any]:
    """Read the paused-set; a missing or corrupt file means nothing is paused."""
    empty: dict[str, Any] = {"projects": [], "processes": []}
    if not path.is_file():
        return empty
    try:
        doc = json.loads(path.read_text())
    except json.JSONDecodeError:
        return empty
    return {"projects": list(doc.get("projects", [])), "processes": list(doc.get("processes", []))}


def merge_state(old: dict[str, Any], plan: Plan) -> dict[str, Any]:
    """Union of what is already paused and the new plan (a second `on` never forgets the first)."""
    procs = {p["pid"]: p for p in old["processes"]}
    procs.update({p["pid"]: {"pid": p["pid"], "match": p["match"], "command": p["command"]} for p in plan.processes})
    return {"projects": sorted({*old["projects"], *plan.projects}), "processes": list(procs.values())}


# ---------------------------------------------------------------- actions


def apply_plan(
    plan: Plan,
    state_path: Path = STATE,
    run: Runner = sh,
    kill: Callable[[int, int], None] = os.kill,
) -> dict[str, Any]:
    """Stop projects, SIGSTOP processes; state is written after each step so a crash still records it."""
    state = load_state(state_path)
    for proj in plan.projects:
        if proj.lower() == FALCON:
            continue
        run(["docker", "compose", "-p", proj, "stop"])
        state = merge_state(state, Plan(projects=[proj]))
        save_state(state, state_path)
    for p in plan.processes:
        try:
            kill(p["pid"], signal.SIGSTOP)
        except OSError:
            continue
        state = merge_state(state, Plan(processes=[p]))
        save_state(state, state_path)
    return state


def restore(
    state_path: Path = STATE,
    run: Callable[[list[str]], int] = run_rc,
    kill: Callable[[int, int], None] = os.kill,
    ps: Callable[[], str] | None = None,
) -> tuple[list[str], list[str]]:
    """Undo what state.json lists; returns (done, failed). Failed entries stay in state.json for a retry."""
    state = load_state(state_path)
    done: list[str] = []
    failed: list[str] = []
    alive = {p["pid"]: p["command"] for p in parse_ps((ps or (lambda: sh(PS_CMD)))())}
    for proj in list(state["projects"]):
        if proj.lower() != FALCON:
            rc = run(["docker", "compose", "-p", proj, "start"])
            if rc != 0:
                failed.append(f"docker compose -p {proj} start (exit {rc})")
                continue
            done.append(f"docker compose -p {proj} start")
        state["projects"].remove(proj)
        save_state(state, state_path)
    for p in list(state["processes"]):
        if alive.get(p["pid"]) == p["command"]:  # pid-reuse guard
            try:
                kill(p["pid"], signal.SIGCONT)
                done.append(f"SIGCONT pid {p['pid']} ({p['match']})")
            except ProcessLookupError:
                pass  # already gone
            except OSError:
                failed.append(f"SIGCONT pid {p['pid']} ({p['match']})")
                continue
        state["processes"].remove(p)
        save_state(state, state_path)
    return done, failed


# ---------------------------------------------------------------- thresholds (pure)


def eval_free_mem(pct: float | None) -> Row:
    why = f"need >= {MIN_FREE_MEM_PCT:.0f}% free or macOS compresses memory and STT/LLM latency spikes"
    if pct is None:
        return Row("free memory", "WARN", "unknown (memory_pressure not readable)", why)
    return Row("free memory", "OK" if pct >= MIN_FREE_MEM_PCT else "FAIL", f"{pct:.0f}% free", why)


def eval_swap(mb: float | None) -> Row:
    why = f"need <= {MAX_SWAP_MB:.0f} MB used; heavy swap makes latency unpredictable"
    if mb is None:
        return Row("swap used", "WARN", "unknown", why)
    return Row("swap used", "OK" if mb <= MAX_SWAP_MB else "FAIL", f"{mb:.0f} MB", why)


def eval_cpu(idle: float | None) -> Row:
    why = f"need >= {MIN_CPU_IDLE_PCT:.0f}% idle so the cascade and STT are not starved"
    if idle is None:
        return Row("cpu idle", "WARN", "unknown", why)
    return Row("cpu idle", "OK" if idle >= MIN_CPU_IDLE_PCT else "FAIL", f"{idle:.0f}% idle", why)


def eval_thermal(text: str) -> Row:
    why = "a CPU speed limit below 100% means the Mac is throttling"
    if not text.strip():
        return Row("thermal", "WARN", "unknown", why)
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", text)
    if m is None:
        return Row("thermal", "OK", "no thermal warning", why)
    lim = int(m.group(1))
    return Row("thermal", "OK" if lim >= 100 else "FAIL", f"CPU speed limit {lim}%", why)


def eval_disk(free_gb: float) -> Row:
    why = f"need >= {MIN_DISK_FREE_GB:.0f} GB for Docker, Ollama and Postgres"
    return Row("disk free", "OK" if free_gb >= MIN_DISK_FREE_GB else "FAIL", f"{free_gb:.0f} GB", why)


def eval_latency(name: str, ms: float | None, limit: float, err: str = "") -> Row:
    why = f"need <= {limit / 1000:.0f} s (the API wait cap); slower looks broken on stage"
    if ms is None:
        return Row(name, "FAIL", err or "failed", why)
    return Row(name, "OK" if ms <= limit else "FAIL", f"{ms:.0f} ms", why)


def eval_containers(lines: list[str]) -> Row:
    """lines are `name<TAB>status` from docker ps for the falcon project."""
    why = "every Falcon container must be Up and healthy"
    if not lines:
        return Row("falcon stack", "FAIL", "no containers running (run `make up`)", why)
    bad = [
        ln.split("\t")[0]
        for ln in lines
        if "unhealthy" in ln or "starting" in ln or not ln.split("\t")[-1].startswith("Up")
    ]
    if bad:
        return Row("falcon stack", "FAIL", f"{len(bad)} of {len(lines)} not healthy: {', '.join(bad[:4])}", why)
    return Row("falcon stack", "OK", f"{len(lines)} containers healthy", why)


def eval_others(projects: list[dict[str, Any]]) -> Row:
    why = "other compose projects compete for RAM and CPU; `make demo-mode-on` pauses them"
    others = [p for p in projects if p["name"] != FALCON and p["running"] > 0]
    if not others:
        return Row("other compose projects", "OK", "none running", why)
    desc = ", ".join(
        f"{p['name']} ({p['running']} containers{', ' + p['mem'] if p.get('mem') else ''})" for p in others
    )
    return Row("other compose projects", "FAIL", desc, why)


def board(rows: list[Row]) -> tuple[str, str]:
    """(text, verdict). READY only if no row is FAIL."""
    verdict = NOT_READY if any(r.status == "FAIL" for r in rows) else READY
    w = max(len(r.name) for r in rows)
    lines = [
        f"{r.status:<4}  {r.name:<{w}}  {r.detail}" + (f"   [{r.why}]" if r.status in ("FAIL", "WARN") else "")
        for r in rows
    ]
    return "\n".join(lines) + f"\n\nDEMO MODE: {verdict}", verdict


# ---------------------------------------------------------------- probes (read-only)


def free_mem_pct() -> float | None:
    m = re.search(r"free percentage:\s*(\d+)%", sh(["memory_pressure"]))
    return float(m.group(1)) if m else None


def swap_used_mb() -> float | None:
    m = re.search(r"used = ([\d.]+)([MG])", sh(["sysctl", "vm.swapusage"]))
    if not m:
        return None
    return float(m.group(1)) * (1024 if m.group(2) == "G" else 1)


def cpu_idle_pct() -> float | None:
    m = re.search(r"([\d.]+)% idle", sh(["top", "-l", "1", "-n", "0"], timeout=15))
    return float(m.group(1)) if m else None


def compose_projects_with_mem() -> list[dict[str, Any]]:
    projects = parse_compose_ls(sh(["docker", "compose", "ls", "--format", "json"]))
    names = sh(["docker", "ps", "--format", '{{.Names}}\t{{.Label "com.docker.compose.project"}}'])
    owner = dict(ln.split("\t", 1) for ln in names.splitlines() if "\t" in ln)
    others = [p for p in projects if p["name"] != FALCON and p["running"] > 0]
    if not others:
        return projects
    mem = sh(["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"], timeout=30)
    per: dict[str, float] = {}
    for ln in mem.splitlines():
        n, _, use = ln.partition("\t")
        m = re.match(r"([\d.]+)([KMG])i?B", use.strip())
        if m and n in owner:
            mult = {"K": 1 / 1024, "M": 1.0, "G": 1024.0}[m.group(2)]
            per[owner[n]] = per.get(owner[n], 0.0) + float(m.group(1)) * mult
    for p in projects:
        if p["name"] in per:
            p["mem"] = f"{per[p['name']]:.0f} MiB"
    return projects


def top_processes(n: int = 5) -> str:
    procs = sorted(parse_ps(sh(PS_CMD)), key=lambda p: -p["rss_kb"])
    rows = [p for p in procs if "falcon" not in p["command"].lower() and "com.docker" not in p["command"]][:n]
    return "; ".join(f"{os.path.basename(p['command'].split(' -')[0])[:28]} {p['rss_kb'] // 1024} MB" for p in rows)


def llm_gate_row() -> Row:
    parts = []
    if shutil.which("llm-gate"):
        parts.append("llm-gate: " + (sh(["llm-gate", "status"]).strip().replace("\n", " | ")[:100] or "no output"))
    try:
        models = httpx.get(f"{OLLAMA_URL}/api/ps", timeout=3).json().get("models", [])
        parts.append("ollama loaded: " + (", ".join(m.get("name", "?") for m in models) or "none"))
    except (httpx.HTTPError, ValueError):
        parts.append("ollama not reachable")
    return Row("LLM gate", "INFO", "; ".join(parts))


def stt_row() -> Row:
    try:
        r = httpx.get(f"{STT_URL}/health", timeout=3)
    except httpx.HTTPError:
        return Row("native STT :8093", "INFO", "not running (voice route unavailable)")
    return Row(
        "native STT :8093", "OK" if r.status_code == 200 else "WARN", f"HTTP {r.status_code}", "voice demo needs STT"
    )


def tunnel_row() -> Row:
    why = "the public URL must answer 200"
    if not TUNNEL_FILE.is_file():
        return Row(
            "public tunnel", "WARN", "data/private/tunnel_url.txt missing (`make tunnel` if the demo is public)", why
        )
    url = TUNNEL_FILE.read_text().strip()
    host = re.sub(r"^https?://", "", url).split("/")[0]
    try:
        code = httpx.get(url, timeout=8, follow_redirects=True).status_code
    except httpx.HTTPError as e:
        return Row("public tunnel", "FAIL", f"{host}: {type(e).__name__}", why)
    return Row("public tunnel", "OK" if code == 200 else "FAIL", f"{host}: HTTP {code}", why)


def api_client() -> tuple[Any, str, str | None]:
    """(ApiClient, gateway URL, API key) built from .env like the other demo tooling."""
    sys.path.insert(0, str(REPO / "scripts"))
    from falcon_demo.common import ApiClient, Endpoints, load_env, pick_key  # type: ignore[import-not-found,unused-ignore]

    env = load_env()
    key, _ = pick_key(env)
    gateway = Endpoints.from_env(env).gateway
    return ApiClient(gateway, key), gateway, key


def timed(fn: Callable[[], Any]) -> tuple[float | None, str]:
    """(milliseconds, '') on success or (None, exception type) on failure."""
    t0 = time.perf_counter()
    try:
        fn()
    except Exception as e:  # noqa: BLE001 - any failure becomes a FAIL row (type only, never a secret)
        return None, type(e).__name__
    return (time.perf_counter() - t0) * 1000, ""


FIXTURE_URL = "http://falcon-demo-bank-secure.test/login"
FIXTURE_MSGS = [
    "عزيزي العميل، حسابك في بنك الصقر التجريبي سيتم تجميده خلال ساعة. أرسل رمز التحقق وادخل على "
    "http://falcon-demo-bank-secure.test/login فوراً",
    "Falcon Demo Bank: your account is limited. Confirm now at http://falcon-demo-bank-secure.test/login",
    "Falcon Demo Bank: your statement is ready in the app. No action needed.",
]


def probe_rows() -> list[Row]:
    nonce = str(int(time.time() * 1000))
    try:
        client, _, _ = api_client()
    except Exception as e:  # noqa: BLE001
        err = type(e).__name__
        return [
            eval_latency("link check", None, MAX_LINK_MS, err),
            eval_latency("message check", None, MAX_MESSAGE_MS, err),
        ]
    link_ms, e1 = timed(lambda: client.check_url(f"{FIXTURE_URL}?dm={nonce}", idem=f"dm-url-{nonce}", wait=8))
    msg_ms, e2 = timed(lambda: client.check_message(f"{FIXTURE_MSGS[1]} ref {nonce}", idem=f"dm-msg-{nonce}", wait=8))
    client.close()
    return [
        eval_latency("link check", link_ms, MAX_LINK_MS, e1),
        eval_latency("message check", msg_ms, MAX_MESSAGE_MS, e2),
    ]


def run_check() -> int:
    """Print the board; return 0 only when READY."""
    label = f"label=com.docker.compose.project={FALCON}"
    falcon = sh(["docker", "ps", "--filter", label, "--format", "{{.Names}}\t{{.Status}}"])
    rows = [eval_containers([ln for ln in falcon.splitlines() if ln.strip()])]
    rows += [eval_free_mem(free_mem_pct()), eval_swap(swap_used_mb()), eval_cpu(cpu_idle_pct())]
    rows += [eval_thermal(sh(["pmset", "-g", "therm"])), eval_disk(shutil.disk_usage(REPO).free / 1e9)]
    rows += [eval_others(compose_projects_with_mem()), Row("top other processes", "INFO", top_processes())]
    rows += [llm_gate_row(), stt_row(), tunnel_row()]
    rows += probe_rows()
    text, verdict = board(rows)
    print(text)
    return 0 if verdict == READY else 1


# ---------------------------------------------------------------- on / off / prewarm


def silent_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    """A mono 16-bit silent WAV."""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _warm(client: Any, text: str, stamp: int, i: int) -> Callable[[], Any]:
    return lambda: client.check_message(text, idem=f"dm-warm-{stamp}-{i}", wait=8)


def prewarm() -> None:
    """Whisper, three fixture checks, the voice web route. Failures are printed, never fatal."""
    print("pre-warm:")
    try:
        httpx.get(f"{STT_URL}/health", timeout=3)
        t0 = time.perf_counter()
        r = httpx.post(f"{STT_URL}/stt", content=silent_wav(), headers={"Content-Type": "audio/wav"}, timeout=60)
        print(f"  whisper: HTTP {r.status_code} in {(time.perf_counter() - t0) * 1000:.0f} ms")
    except httpx.HTTPError:
        print("  whisper: native STT not running, skipped")
    try:
        client, gateway, _ = api_client()
        stamp = int(time.time())
        for i in range(3):
            text = FIXTURE_MSGS[i]
            ms, err = timed(_warm(client, text, stamp, i))
            print(f"  check warm-up {i + 1}: " + (f"{ms:.0f} ms" if ms is not None else f"failed ({err})"))
        client.close()
        r = httpx.get(f"{gateway}/voice", timeout=10, verify=False)  # noqa: S501 - local CA gateway only
        print(f"  voice web route: HTTP {r.status_code}" + (" (route not present yet)" if r.status_code == 404 else ""))
    except Exception as e:  # noqa: BLE001
        print(f"  check path / voice route: failed ({type(e).__name__})")


def cmd_on(yes: bool) -> int:
    plan = build_plan(sh(["docker", "compose", "ls", "--format", "json"]), sh(PS_CMD), load_config(), own_pids())
    print("Demo mode would pause (the falcon project is never touched):")
    for ln in plan.lines():
        print("  " + ln)
    if not yes:
        print("\nNothing done. Re-run with --yes (or CONFIRM=yes) to act.")
        return 2
    if not plan.empty():
        apply_plan(plan)
        print(f"\nPaused. State recorded in {STATE.relative_to(REPO)}. Undo with `make demo-mode-off`.")
    prewarm()
    print()
    return run_check()


def cmd_off() -> int:
    done, failed = restore()
    print("\n".join(done) if done else ("nothing to restore" if not failed else ""))
    for f in failed:
        print(f"FAILED: {f} (kept in state.json; run `make demo-mode-off` again)")
    return 1 if failed else 0


# ---------------------------------------------------------------- rehearsal

LINE_EN = "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens"
LINE_AR = "يا فالكون، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر"


def rehearsal_messages(kit: Path = KIT_MESSAGES) -> list[str]:
    """First three demo-kit messages, else the built-in Falcon Demo Bank fixtures."""
    files = sorted(kit.glob("*.txt"))[:3] if kit.is_dir() else []
    msgs = [f.read_text().strip() for f in files]
    return msgs if len(msgs) == 3 else FIXTURE_MSGS


def cmd_rehearsal() -> int:
    if not shutil.which("say"):
        print("macOS `say` not found; cannot generate speech.")
        return 1
    try:
        client, gateway, key = api_client()
        client.close()
    except Exception as e:  # noqa: BLE001
        print(f"API client unavailable: {type(e).__name__}")
        return 1
    out = Path(tempfile.mkdtemp(prefix="dm-voice-"))
    for lang, text, voice in (("en", LINE_EN, None), ("ar", LINE_AR, "Majed")):
        wav = out / f"{lang}.wav"
        cmd = ["say", "-o", str(wav), "--data-format=LEI16@16000", *(["-v", voice] if voice else []), text]
        if subprocess.run(cmd, capture_output=True, check=False).returncode != 0:  # noqa: S603
            hint = f" (is the '{voice}' voice installed? Settings > Accessibility > Spoken Content)" if voice else ""
            print(f"{lang}: `say` failed{hint}")
            continue
        t0 = time.perf_counter()
        try:
            r = httpx.post(
                f"{gateway}/v1/voice/utterance",
                files={"audio": (f"{lang}.wav", wav.read_bytes(), "audio/wav")},
                data={"lang_hint": lang},
                headers={"X-API-Key": key or ""},
                timeout=60,
                verify=False,  # noqa: S501 - local CA gateway only
            )
        except httpx.HTTPError as e:
            print(f"{lang}: API unreachable ({type(e).__name__})")
            continue
        ms = (time.perf_counter() - t0) * 1000
        if r.status_code in (404, 405):
            print(f"{lang}: SKIPPED, /v1/voice/utterance is not merged on this stack (HTTP {r.status_code}).")
            continue
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        print(
            f"{lang}: HTTP {r.status_code}, wake={body.get('wake')}, intent={body.get('intent')}, latency={ms:.0f} ms"
        )
    msgs = rehearsal_messages()
    if shutil.which("pbcopy"):
        subprocess.run(["pbcopy"], input="\n\n----\n\n".join(msgs), text=True, check=False)  # noqa: S603, S607
        print(f"Clipboard: {len(msgs)} demo messages copied (separated by ----).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="demo_mode")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    on = sub.add_parser("on")
    on.add_argument("--yes", action="store_true")
    sub.add_parser("off")
    sub.add_parser("rehearsal")
    a = ap.parse_args(argv)
    if a.cmd == "check":
        return run_check()
    if a.cmd == "on":
        return cmd_on(a.yes or os.environ.get("CONFIRM") == "yes")
    if a.cmd == "off":
        return cmd_off()
    return cmd_rehearsal()


if __name__ == "__main__":
    sys.exit(main())
