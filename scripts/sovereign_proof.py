#!/usr/bin/env python3
"""Sovereign-mode proof run: one artifact that says what ran fully local and what still needed the internet.

What it does:
    Against a RUNNING isolated stack that was started with FL_SOVEREIGN_MODE=1 and NO ANTHROPIC_API_KEY, it
    1. audits the services' environment (non-secret keys only: sovereign flag, key present yes/no, local base URL
       and model, the Anthropic base-URL sink),
    2. warms the local model and times one tiny completion,
    3. seeds, then runs the six demo scenarios and the Sentinel scene (the same code as `make demo`) with a time
       per scenario and the verdict's own model_route,
    4. sends one spoken utterance (macOS `say`, synthetic) through /v1/voice/utterance (container faster-whisper),
    5. reads the Sentinel incident of the scene and records who wrote its summary (llm or template, and route),
    6. counts the "llm call" log lines of the stack by role, route and model, and scrapes the fl_ LLM metrics,
    7. runs the egress audit: hits on the Anthropic sink, the key flag, any mention of a cloud LLM host in the
       service logs, and the hosts the egress proxies actually contacted.
    Everything in the artifact is measured by this run; nothing is typed in. A failed run is written as failed.

When to use it:
    Before claiming "runs fully locally" anywhere. The claim may only be what the published artifact shows.

How to run:
    (stack up with COMPOSE_PROJECT_NAME=flsov, ports from .env, OLLAMA_BASE_URL/FL_LOCAL_MODEL set for the model)
    PYTHONPATH=scripts uv run python scripts/sovereign_proof.py --label inkling-2-mini-chat \\
        --model inkling-2-mini-chat --host-llm-url http://127.0.0.1:11434 \\
        --sink-log /path/sink.log --prom-url http://127.0.0.1:53090 [--publish]

Inputs:
    .env of the repo root (gateway port, keys), the running compose project, an Anthropic sink log (one JSON
    line per request that reached the sink; a tiny HTTP server the stack's ANTHROPIC_BASE_URL points at).

Outputs / side effects:
    evals/results/published/sovereign/sovereign_<label>_<UTC ts>.json with --publish (else under
    evals/results/sovereign_proof/). The checks it sends are labelled source=replay and are synthetic.

Safety notes:
    Reads secret values only to authenticate, never prints or stores them. No live phishing URLs: the scenarios use
    the invented "Falcon Demo Bank" fixtures on the internal network.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from falcon_demo import scenarios as sc
from falcon_demo.common import load_env

ROOT = Path(__file__).resolve().parents[1]
CLOUD_LLM_HOSTS = (
    "api.anthropic.com",
    "anthropic.com",
    "api.openai.com",
    "openai.com",
    "generativelanguage.googleapis.com",
    "api.mistral.ai",
    "api.cohere",
    "api.groq.com",
    "openrouter.ai",
    "api.together",
    "api.x.ai",
)
LLM_SERVICES = ("api", "worker", "sentinel", "mcp")
ENV_KEYS = (
    "FL_SOVEREIGN_MODE",
    "OLLAMA_BASE_URL",
    "FL_LOCAL_MODEL",
    "FL_LOCAL_VISION_MODEL",
    "FL_LOCAL_NO_THINK",
    "ANTHROPIC_BASE_URL",
)
UTTERANCE = "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens"
# Invented, Falcon Demo Bank only. Used to push at least one check into the model-judged band.
PROBE_TEXTS = (
    "Falcon Demo Bank: your account may need a quick review. Please check your details at your earliest convenience.",
    "Hello, this is the Falcon Demo Bank courier desk. A parcel is waiting; confirm the delivery slot with us today.",
)


class FreshRunner(sc.Runner):
    """Runner that tags each message and email with a one-off reference, so a repeat run is never answered from
    the API's result cache (the scenario text is otherwise identical to `make demo`)."""

    def message(self, text: str) -> dict[str, Any]:
        return super().message(f"{text}\n[ref {secrets.token_hex(4)}]")

    def email(self, eml: str) -> dict[str, Any]:
        return super().email(eml.rstrip("\n") + f"\nref {secrets.token_hex(4)}\n")


def compose(*args: str, check: bool = True) -> str:
    p = subprocess.run(["docker", "compose", *args], capture_output=True, text=True, cwd=ROOT, check=False)  # noqa: S603, S607
    if check and p.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)} -> {p.returncode}: {p.stderr.strip()[:300]}")
    return p.stdout + (p.stderr if not check else "")


def env_audit() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for svc in LLM_SERVICES:
        raw = compose("exec", "-T", svc, "env")
        kv = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
        row: dict[str, Any] = {k: kv.get(k) for k in ENV_KEYS}
        row["ANTHROPIC_API_KEY_present"] = bool(kv.get("ANTHROPIC_API_KEY"))
        out[svc] = row
    return out


def warm(host_url: str, model: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    try:
        r = httpx.post(
            host_url.rstrip("/") + "/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with the word OK."}],
                "max_tokens": 8,
            },
            timeout=600,
        )
        return {"ok": r.status_code == 200, "status": r.status_code, "seconds": round(time.perf_counter() - t0, 1)}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": type(exc).__name__, "seconds": round(time.perf_counter() - t0, 1)}


def run_scenarios(runner: sc.Runner) -> list[dict[str, Any]]:
    plan: list[tuple[str, Any]] = [(n, f) for n, f in sc.SCENARIOS]
    rows: list[dict[str, Any]] = []
    for name, fn in plan + [("S Sentinel scene", sc.sentinel_scene)]:
        t0 = time.perf_counter()
        row: dict[str, Any] = {"name": name}
        try:
            doc, note = fn(runner)
            row.update(result="PASS", verdict=doc.get("verdict"), verdict_id=doc.get("verdict_id"), note=note)
            for k in ("model_route", "tier_reached", "latency_ms", "degraded"):
                if k in doc:
                    row[k] = doc[k]
        except sc.Scenario as exc:
            row.update(result="SKIPPED", note=str(exc))
        except (sc.CheckFailed, httpx.HTTPError, KeyError, subprocess.CalledProcessError) as exc:
            row.update(result="FAIL", note=f"{type(exc).__name__}: {exc}"[:320])
        row["wall_s"] = round(time.perf_counter() - t0, 1)
        rows.append(row)
        print(f"  {name:<22} {row['result']:<8} {row.get('verdict', '')!s:<18} {row['wall_s']}s  {row.get('note', '')}")
    return rows


def run_probes(runner: sc.Runner) -> list[dict[str, Any]]:
    rows = []
    for text in PROBE_TEXTS:
        t0 = time.perf_counter()
        try:
            doc = runner.message(text)
            rows.append(
                {
                    "kind": "message_probe",
                    "verdict": doc.get("verdict"),
                    "model_route": doc.get("model_route"),
                    "tier_reached": doc.get("tier_reached"),
                    "latency_ms": doc.get("latency_ms"),
                    "wall_s": round(time.perf_counter() - t0, 1),
                }
            )
        except (sc.CheckFailed, httpx.HTTPError, KeyError) as exc:
            rows.append({"kind": "message_probe", "error": f"{type(exc).__name__}: {exc}"[:200]})
    return rows


def voice_check(runner: sc.Runner) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "u.wav"
        p = subprocess.run(  # noqa: S603
            ["say", "-v", "Samantha", "--data-format=LEI16@16000", "-o", str(wav), UTTERANCE],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if p.returncode != 0:
            return {"ok": False, "error": "macOS `say` unavailable; no utterance generated"}
        with wave.open(str(wav), "rb") as w:
            dur = w.getnframes() / w.getframerate()
        t0 = time.perf_counter()
        r = runner.c.post(
            "/v1/voice/utterance",
            files={"audio": ("u.wav", wav.read_bytes(), "audio/wav")},
            data={"lang_hint": "en"},
            headers={k: v for k, v in runner._headers().items() if k == "X-API-Key"},  # noqa: SLF001
        )
        wall = round(time.perf_counter() - t0, 2)
    out: dict[str, Any] = {
        "provenance": "SYNTHETIC speech from macOS `say` (not a human recording)",
        "audio_seconds": round(dur, 1),
        "http_status": r.status_code,
        "wall_s": wall,
    }
    if r.status_code == 200:
        b = r.json()
        out.update({k: b.get(k) for k in ("model", "wake", "intent", "lang", "duration_ms")})
        out["transcript"] = b.get("transcript")
        out["ok"] = bool(b.get("wake"))
    else:
        out["ok"] = False
        out["error"] = r.text[:200]
    return out


def sentinel_summary(runner: sc.Runner, rows: list[dict[str, Any]], started: datetime) -> dict[str, Any]:
    scene = next((r for r in rows if r["name"].startswith("S ")), None)
    if not scene or scene.get("result") != "PASS":
        return {"ok": False, "reason": "Sentinel scene did not pass"}
    op = runner.env.get("FL_OPERATOR_KEY", "")
    r = runner.c.get(f"/v1/incidents/{scene['verdict_id']}", headers={"Authorization": f"Bearer {op}"})
    if r.status_code != 200:
        return {"ok": False, "reason": f"GET incident -> HTTP {r.status_code}"}
    inc = r.json()
    s = inc.get("summary") or {}
    created = datetime.fromisoformat(str(inc.get("created_at", "1970-01-01T00:00:00+00:00")).replace("Z", "+00:00"))
    return {
        "created_during_this_run": created >= started,
        "incident_id": inc.get("incident_id"),
        "type": inc.get("type"),
        "summary_generated_by": s.get("generated_by"),
        "summary_model_route": s.get("model_route"),
        "severity_reason_generated_by": (inc.get("severity_reason") or {}).get("generated_by"),
        "ok": created >= started and s.get("generated_by") == "llm" and s.get("model_route") == "local",
    }


def log_llm_calls(since: str) -> dict[str, Any]:
    text = compose("logs", "--no-log-prefix", "--since", since, *LLM_SERVICES, check=False)
    calls: Counter[tuple[str, str, str]] = Counter()
    ms: dict[tuple[str, str, str], list[float]] = {}
    failed: Counter[tuple[str, str, str]] = Counter()
    for line in text.splitlines():
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if j.get("msg") == "llm call":
            k = (str(j.get("role")), str(j.get("route")), str(j.get("model")))
            calls[k] += 1
            ms.setdefault(k, []).append(float(j.get("ms", 0)))
        elif j.get("msg") == "llm call failed":
            failed[(str(j.get("role")), str(j.get("route")), str(j.get("model")))] += 1
    return {
        "ok_calls": [
            {
                "role": k[0],
                "route": k[1],
                "model": k[2],
                "n": n,
                "p50_ms": round(statistics.median(ms[k])),
                "max_ms": round(max(ms[k])),
            }
            for k, n in sorted(calls.items())
        ],
        "failed_calls": [{"role": k[0], "route": k[1], "model": k[2], "n": n} for k, n in sorted(failed.items())],
        "log_text": text,
    }


def prom(prom_url: str, q: str) -> list[dict[str, Any]]:
    try:
        r = httpx.get(prom_url.rstrip("/") + "/api/v1/query", params={"query": q}, timeout=15)
        return [
            {**x["metric"], "value": float(x["value"][1])}
            for x in r.json()["data"]["result"]
            if float(x["value"][1]) > 0
        ]
    except (httpx.HTTPError, KeyError, ValueError):
        return []


def egress_hosts(svc: str) -> list[str]:
    """Hosts the proxy contacted or refused, from its structured log (host field names vary; match both)."""
    hosts: set[str] = set()
    for line in compose("logs", "--no-log-prefix", svc, check=False).splitlines():
        if not line.startswith("{"):
            continue
        try:
            j = json.loads(line)
        except ValueError:
            continue
        for k in ("host", "dest", "target", "destination"):
            if isinstance(j.get(k), str):
                hosts.add(re.sub(r":\d+$", "", j[k]))
    return sorted(hosts)


def classify_hosts(hosts: list[str]) -> dict[str, Any]:
    """Summarise proxy destinations: lookups are listed, page-visit hosts (replay corpus + sub-resources) counted."""
    lookup = [h for h in hosts if h == "crt.sh" or h.startswith("rdap.") or h == "data.iana.org" or "whois" in h]
    cloud = [h for h in hosts if any(h == c or h.endswith("." + c) for c in CLOUD_LLM_HOSTS)]
    return {
        "hosts_total": len(hosts),
        "lookup_hosts": lookup,
        "cloud_llm_hosts": cloud,
        "page_visit_hosts_count": len(hosts) - len(lookup),
        "note": "page-visit hosts are sites the sandbox visited passively during the run plus their "
        "sub-resources; they are lookups about the checked site, not user data and not LLM traffic",
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True, help="file label, e.g. inkling-2-mini-chat")
    ap.add_argument("--model", required=True, help="local model id the stack is configured with")
    ap.add_argument("--host-llm-url", required=True, help="host-side URL of that model server (warm-up only)")
    ap.add_argument("--sink-log", required=True, type=Path)
    ap.add_argument("--sink-url", default="http://127.0.0.1:18999", help="host URL of the sink, for the self-test")
    ap.add_argument("--prom-url", default="")
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)

    started = datetime.now(UTC)
    env = load_env()
    artifact: dict[str, Any] = {
        "kind": "sovereign_proof",
        "created_at": started.isoformat(timespec="seconds"),
        "git_sha": subprocess.run(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        ).stdout.strip(),
        "provenance": "Run on one developer machine (macOS host, Docker, local model servers). Fixtures are the "
        "invented Falcon Demo Bank; speech is synthetic (macOS `say`). Not a production deployment.",
        "route": "local (FL_SOVEREIGN_MODE=1, no ANTHROPIC_API_KEY)",
        "local_model": a.model,
        "model_server": a.host_llm_url,
        "status": "failed",
    }

    def sink_lines() -> int:
        return len(a.sink_log.read_text().splitlines()) if a.sink_log.exists() else 0

    n0 = sink_lines()
    try:
        httpx.get(a.sink_url.rstrip("/") + "/selftest", timeout=5)
    except httpx.HTTPError:
        pass
    sink_selftest_ok = sink_lines() == n0 + 1  # the sink is listening and logging
    sink_before = sink_lines()
    try:
        artifact["service_env"] = env_audit()
        print("warming the local model ...")
        artifact["warmup"] = warm(a.host_llm_url, a.model)
        print(f"  warm-up: {artifact['warmup']}")
        since = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        runner = FreshRunner(env)
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "falcon_demo", "seed"], cwd=ROOT, check=False, capture_output=True, timeout=600
        )
        print("scenarios:")
        rows = run_scenarios(runner)
        artifact["scenarios"] = rows
        artifact["scenario_counts"] = dict(Counter(r["result"] for r in rows))
        artifact["message_probes"] = run_probes(runner)
        print("voice ...")
        artifact["voice"] = voice_check(runner)
        print(f"  {artifact['voice']}")
        artifact["sentinel_incident"] = sentinel_summary(runner, rows, started)
        time.sleep(20)  # one Prometheus scrape
        calls = log_llm_calls(since)
        log_text = calls.pop("log_text")
        artifact["llm_calls_from_logs"] = calls
        if a.prom_url:
            artifact["metrics"] = {
                "fl_llm_calls_total": prom(a.prom_url, "sum by (role,route,outcome) (fl_llm_calls_total)"),
                "fl_llm_tokens_total_by_model": prom(a.prom_url, "sum by (model,role) (fl_llm_tokens_total)"),
                "fl_llm_results_total": prom(a.prom_url, "sum by (role,status) (fl_llm_results_total)"),
                "fl_sentinel_text_total": prom(a.prom_url, "sum by (task,generated_by) (fl_sentinel_text_total)"),
                "fl_sentinel_llm_calls_total": prom(a.prom_url, "sum by (task,outcome) (fl_sentinel_llm_calls_total)"),
            }
        sink_hits = len(a.sink_log.read_text().splitlines()) - sink_before if a.sink_log.exists() else 0
        all_logs = compose("logs", "--no-log-prefix", "--since", since, check=False).lower()
        mentions = {h: all_logs.count(h) for h in CLOUD_LLM_HOSTS if h in all_logs}
        routes = {c["route"] for c in calls["ok_calls"]} | {c["route"] for c in calls["failed_calls"]}
        envs = artifact["service_env"]
        artifact["egress_audit"] = {
            "anthropic_api_key_present_in_any_llm_service": any(e["ANTHROPIC_API_KEY_present"] for e in envs.values()),
            "sovereign_flag_in_every_llm_service": all(
                str(e["FL_SOVEREIGN_MODE"]).lower() in ("1", "true") for e in envs.values()
            ),
            "anthropic_sink_selftest_ok": sink_selftest_ok,
            "anthropic_sink_hits": sink_hits,
            "sink_note": "ANTHROPIC_BASE_URL of api/worker/sentinel/mcp points at a host sink that counts requests; "
            "0 means no SDK call to a cloud LLM was attempted.",
            "cloud_llm_host_mentions_in_service_logs": mentions,
            "llm_routes_seen_in_logs": sorted(routes),
            "egress_proxy": classify_hosts(egress_hosts("egress-proxy")),
            "voice_egress_hosts": egress_hosts("voice-egress"),
            "log_lines_scanned_bytes": len(log_text) + len(all_logs),
        }
        ea = artifact["egress_audit"]
        local_ok = (
            bool(calls["ok_calls"])
            and routes <= {"local"}
            and all(c["model"] == a.model for c in calls["ok_calls"] if c["role"] != "vision")
        )
        no_cloud = (
            not ea["anthropic_api_key_present_in_any_llm_service"]
            and ea["sovereign_flag_in_every_llm_service"]
            and sink_selftest_ok
            and sink_hits == 0
            and not mentions
        )
        failures = [r["name"] for r in rows if r["result"] != "PASS"]
        reasons = []
        if failures:
            reasons.append(f"scenarios not passed: {failures}")
        if not local_ok:
            reasons.append("no successful local LLM call with the expected model, or a non-local route was seen")
        if not no_cloud:
            reasons.append("egress audit found a cloud-LLM indicator")
        if not artifact["voice"].get("ok"):
            reasons.append("voice utterance did not pass")
        if not artifact["sentinel_incident"].get("ok"):
            reasons.append("Sentinel summary was not written by the local LLM")
        artifact["status"] = "passed" if not reasons else "failed"
        artifact["failure_reasons"] = reasons
    except Exception as exc:  # noqa: BLE001 - a failed run must still be written down
        artifact["failure_reasons"] = [f"{type(exc).__name__}: {exc}"[:400]]
    artifact["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    artifact["caveats"] = [
        "Sovereign mode keeps the user's text and the model prompts on the machine; not every lookup is offline.",
        "Still needs the internet: RDAP/WHOIS and certificate lookups about the checked domain, reputation feeds, and "
        "the sandbox's one passive visit to the checked site (all via the filtering egress proxy). These carry the "
        "URL's hostname, not the user's messages or the LLM prompts.",
        "The container speech model downloads its weights once from huggingface.co through its own allow-listed proxy; "
        "audio then never leaves the machine.",
        "Everything ran on one machine with fixtures; speech is synthetic; latencies are for this hardware and load.",
    ]
    ts = started.strftime("%Y%m%dT%H%M%SZ")
    outdir = (
        ROOT
        / "evals"
        / "results"
        / ("published" if a.publish else "")
        / ("sovereign" if a.publish else "sovereign_proof")
    )
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"sovereign_{a.label}_{ts}.json"
    path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n")
    print(f"{artifact['status'].upper()}: {path}")
    for r in artifact.get("failure_reasons", []):
        print("  -", r)
    return 0 if artifact["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
