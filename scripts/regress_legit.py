#!/usr/bin/env python3
"""False-positive regression against a RUNNING stack: `make regress-legit LIVE=1`.

Usage: FL_GATEWAY_URL=https://localhost:8443 python scripts/regress_legit.py [--n 30] [--delay 1.0]

Submits a deterministic sample of known-legitimate URLs (evals/datasets/legit_urls.csv, refanged in memory
only) one at a time and fails (exit 1) if any final verdict is suspicious or dangerous. Prints counts only,
never the URLs. Rate-limit friendly: sequential with a delay.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("FL_GATEWAY_URL", "https://localhost:8443").rstrip("/")
TIMEOUT_S = 90


def sample(n: int) -> list[str]:
    with (ROOT / "evals" / "datasets" / "legit_urls.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    pool = [r["url"].replace("hxxp", "http", 1) for r in rows if r["category"] in ("popular", "official_gov")]
    step = max(1, len(pool) // n)
    return pool[::step][:n]


def check(c: httpx.Client, url: str) -> dict[str, object]:
    r = c.post("/v1/check/url", json={"url": url}, timeout=15)
    r.raise_for_status()
    vid = r.json()["verdict_id"]
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        g = c.get(f"/v1/verdicts/{vid}", timeout=10)
        if g.status_code == 200 and g.json().get("final"):
            return dict(g.json())
        time.sleep(0.5)
    raise TimeoutError("no final verdict")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--delay", type=float, default=1.0)
    args = ap.parse_args()
    counts: Counter[str] = Counter()
    degraded = 0
    c = httpx.Client(base_url=BASE, verify=False, timeout=15)  # noqa: S501 - local CA
    for url in sample(args.n):
        try:
            d = check(c, url)
            counts[str(d["verdict"])] += 1
            degraded += bool(d.get("degraded"))
        except Exception as exc:  # noqa: BLE001
            counts[f"error:{type(exc).__name__}"] += 1
        time.sleep(args.delay)
    bad = counts["suspicious"] + counts["dangerous"]
    print(f"regress-legit: n={sum(counts.values())} {dict(counts)} degraded={degraded} false_positives={bad}")
    return 1 if bad or any(k.startswith("error:") for k in counts) else 0


if __name__ == "__main__":
    sys.exit(main())
