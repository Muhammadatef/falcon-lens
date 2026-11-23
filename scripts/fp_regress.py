#!/usr/bin/env python3
"""False-positive regression against a RUNNING stack: `LIVE=1 make regress-legit`.

Usage: FL_GATEWAY_URL=https://localhost:8443 python scripts/fp_regress.py [--set heldout_legit_2.csv] [--n 30]
       [--seed S] [--workers 3] [--delay 0.5] [--target 0.02] [--out PATH]

Samples ``--n`` domains (``--n 0`` = the whole set) from a HELD-OUT legitimate set in evals/datasets (seeded Tranco
samples built by build_heldout_legit.py, never used for tuning), submits ``https://<domain>/`` through the normal
pipeline and writes a result artifact (default evals/results/published/fp_regress/<sha>_<UTC>.json) with the head
commit sha, set, seed, n, verdict counts, degraded reasons and the false-positive rate with a bootstrap 95% CI.
Prints counts only, never the URLs.

Exit status: 1 on any errored check, or when the LOWER bound of the CI exceeds ``--target`` (default 0.02, the
EVALS.md FPR target), i.e. the false-positive rate is significantly above target. A single flagged site does not
fail the run: with n=30 a lone hit is within noise.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("FL_GATEWAY_URL", "https://localhost:8443").rstrip("/")
TIMEOUT_S = 120
DEFAULT_SET = "heldout_legit_2.csv"
DEFAULT_SEED = 20261124


def load_set(name: str) -> tuple[list[str], dict[str, str]]:
    """URLs plus, when the set has the column, ``serves_web`` ("1" web page / "0" no web host) per URL."""
    with (ROOT / "evals" / "datasets" / name).open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    urls = [f"https://{r['domain']}/" for r in rows]
    web = {u: r["serves_web"] for u, r in zip(urls, rows, strict=True) if r.get("serves_web") in ("0", "1")}
    return urls, web


def set_seed(name: str) -> int | None:
    """The seed the held-out set was DRAWN with (column ``seed`` of the csv); None when the set has no such column."""
    with (ROOT / "evals" / "datasets" / name).open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            s = r.get("seed", "")
            return int(s) if s.isdigit() else None
    return None


HTTP_429 = [0]  # responses with status 429 seen by this run (a fresh stack with no rate-limit pressure must show 0)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% interval of a proportion (small-n friendly; reported next to the bootstrap interval)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(res: list[dict[str, Any]]) -> dict[str, Any]:
    flagged = [int(r["verdict"] in ("suspicious", "dangerous")) for r in res]
    lo, hi = bootstrap_ci(flagged)
    return {
        "n": len(res),
        "counts": dict(Counter(r["verdict"] for r in res)),
        "degraded": sum(r["degraded"] for r in res),
        "false_positive_rate": {
            "value": round(sum(flagged) / max(1, len(flagged)), 4),
            "ci95": [round(lo, 4), round(hi, 4)],
            "wilson95": [round(x, 4) for x in wilson(sum(flagged), len(flagged))],
        },
        "false_dangerous": sum(r["verdict"] == "dangerous" for r in res),
        "static_fallback": sum(bool(r.get("static_fallback")) for r in res),
        "partial_reads": sum(bool(r.get("partial")) for r in res),
    }


def head_sha() -> str:
    try:
        sha = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()  # fmt: skip
        dirty = subprocess.run(  # noqa: S603
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()  # fmt: skip
        return sha + ("-dirty" if dirty else "")
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def check(url: str, delay: float) -> dict[str, Any]:
    time.sleep(delay)
    with httpx.Client(base_url=BASE, verify=False, timeout=15) as c:  # noqa: S501 - local CA
        r = c.post("/v1/check/url", json={"url": url})
        if r.status_code == 429:
            HTTP_429[0] += 1
        r.raise_for_status()
        vid = r.json()["verdict_id"]
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            g = c.get(f"/v1/verdicts/{vid}", timeout=10)
            if g.status_code == 429:
                HTTP_429[0] += 1
            if g.status_code == 200 and g.json().get("final"):
                d = g.json()
                risk = sorted((e for e in d.get("evidence", []) if e.get("weight", 0) > 0), key=lambda e: -e["weight"])
                return {
                    "verdict": d["verdict"],
                    "degraded": bool(d.get("degraded")),
                    "tier": d.get("tier_reached"),
                    "degraded_reasons": d.get("degraded_reasons") or [],
                    "risk_signals": [e["signal"] for e in risk[:3]],
                    "risk_score": d.get("risk_score"),
                    # read before the page finished loading (page.truncated with partial=true)
                    "static_fallback": any(e.get("signal") == "page.static_fallback" for e in d.get("evidence", [])),
                    "partial": any(
                        e.get("signal") == "page.truncated" and (e.get("observed") or {}).get("partial") is True
                        for e in d.get("evidence", [])
                    ),
                }
            time.sleep(0.5)
    raise TimeoutError("no final verdict")


def bootstrap_ci(flags: list[int], n_boot: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    n = len(flags)
    if n == 0:
        return (0.0, 0.0)
    stats = sorted(sum(flags[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default=DEFAULT_SET)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--target", type=float, default=0.02)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    pool, web = load_set(a.set)
    drawn = set_seed(a.set)
    if drawn is not None and a.n <= 0:
        a.seed = drawn  # a full-set run samples nothing: record the seed the set was drawn with
    urls = pool if a.n <= 0 else random.Random(a.seed).sample(pool, min(a.n, len(pool)))  # noqa: S311
    print(f"fp-regress: gateway={BASE} set={a.set} sample={len(urls)}/{len(pool)} seed={a.seed}", flush=True)

    def one(u: str) -> dict[str, Any]:
        try:
            return {**check(u, a.delay), "url": u}
        except Exception as exc:  # noqa: BLE001
            return {"verdict": f"error:{type(exc).__name__}", "degraded": False, "tier": None, "url": u}

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(one, urls))
    counts = Counter(r["verdict"] for r in res)
    flagged = [int(r["verdict"] in ("suspicious", "dangerous")) for r in res]
    lo, hi = bootstrap_ci(flagged)
    degraded = sum(r["degraded"] for r in res)
    errors = sum(v for k, v in counts.items() if k.startswith("error:"))
    fpr = sum(flagged) / max(1, len(flagged))
    why = Counter(r for x in res for r in x.get("degraded_reasons", []))
    top = Counter(x["risk_signals"][0] for x in res if x["verdict"] != "no_warning_signs" and x.get("risk_signals"))
    print(
        f"fp-regress: n={len(res)} {dict(counts)} degraded={degraded} errors={errors} "
        f"fpr={fpr:.4f} ci95=[{lo:.4f},{hi:.4f}] target={a.target}"
    )
    print(
        f"partial_reads={sum(bool(r.get('partial')) for r in res)} degraded_reasons={dict(why)} "
        f"top_risk_signal_of_flagged={dict(top)}"
    )
    if web:
        for flag, label in (("1", "serves_web_page"), ("0", "no_web_host")):
            sub_res = rate([r for r in res if web.get(r["url"]) == flag])
            print(f"fp-regress[{label}]: {sub_res}")
    sha = head_sha()
    artifact = {
        "kind": "fp_regress",
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": sha,
        "set": a.set,
        "seed": a.seed,
        "n": len(res),
        "pool": len(pool),
        "counts": dict(counts),
        "false_positive_rate": {"value": round(fpr, 4), "ci95": [round(lo, 4), round(hi, 4)], "n_boot": 2000},
        "target": a.target,
        "degraded": degraded,
        "errors": errors,
        "degraded_reasons": dict(why),
        "partial_reads": sum(bool(r.get("partial")) for r in res),
        "static_fallback_reads": sum(bool(r.get("static_fallback")) for r in res),
        "false_dangerous": counts.get("dangerous", 0),
        "http_429": HTTP_429[0],
        "wilson95": [round(x, 4) for x in wilson(sum(flagged), len(flagged))],
        "top_risk_signal_of_flagged": dict(top),
        "by_tier": dict(Counter(str(r["tier"]) for r in res)),
        "items": [
            {
                "domain": r["url"].split("//", 1)[-1].rstrip("/"),
                "serves_web": web.get(r["url"]),
                "verdict": r["verdict"],
                "tier": r.get("tier"),
                "degraded_reasons": r.get("degraded_reasons", []),
                "partial": bool(r.get("partial", False)),
                "static_fallback": bool(r.get("static_fallback", False)),
            }
            for r in res
        ],
        "by_serves_web": {
            label: rate([r for r in res if web.get(r["url"]) == flag])
            for flag, label in (("1", "serves_web_page"), ("0", "no_web_host"))
        }
        if web
        else None,
    }
    out = (
        Path(a.out)
        if a.out
        else ROOT
        / "evals"
        / "results"
        / "published"
        / "fp_regress"
        / (f"{sha[:12]}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
    print(f"fp-regress: artifact {out}")
    return 1 if errors or lo > a.target else 0


if __name__ == "__main__":
    sys.exit(main())
