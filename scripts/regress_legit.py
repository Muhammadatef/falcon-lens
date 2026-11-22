#!/usr/bin/env python3
"""False-positive regression against a RUNNING stack: `LIVE=1 make regress-legit`.

Usage: FL_GATEWAY_URL=https://localhost:8443 python scripts/regress_legit.py [--n 30] [--seed S] [--workers 3]
       [--delay 0.5] [--out result.json]

Samples ``--n`` domains AT RANDOM from the held-out legitimate set (evals/datasets/heldout_legit.csv, built by
build_heldout_legit.py: seeded Tranco sample never used for tuning). The sampling seed is random per run unless
``--seed`` is given, and is always printed so a failing run can be replayed. Submits ``https://<domain>/`` through
the normal pipeline and fails (exit 1) if any final verdict is suspicious or dangerous (or a check errors).
Prints counts, a bootstrap 95% CI of the false-positive rate and the seed; never the URLs. ``--n 0`` = whole set.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("FL_GATEWAY_URL", "https://localhost:8443").rstrip("/")
TIMEOUT_S = 120


def heldout() -> list[str]:
    with (ROOT / "evals" / "datasets" / "heldout_legit.csv").open(newline="", encoding="utf-8") as f:
        return [f"https://{r['domain']}/" for r in csv.DictReader(f)]


def check(url: str, delay: float) -> dict[str, Any]:
    time.sleep(delay)
    with httpx.Client(base_url=BASE, verify=False, timeout=15) as c:  # noqa: S501 - local CA
        r = c.post("/v1/check/url", json={"url": url})
        r.raise_for_status()
        vid = r.json()["verdict_id"]
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            g = c.get(f"/v1/verdicts/{vid}", timeout=10)
            if g.status_code == 200 and g.json().get("final"):
                d = g.json()
                return {"verdict": d["verdict"], "degraded": bool(d.get("degraded")), "tier": d.get("tier_reached")}
            time.sleep(0.5)
    raise TimeoutError("no final verdict")


def bootstrap_ci(flags: list[int], n_boot: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(flags)
    if n == 0:
        return (0.0, 0.0)
    stats = sorted(sum(flags[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (stats[int(0.025 * n_boot)], stats[int(0.975 * n_boot) - 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    seed = a.seed if a.seed is not None else random.SystemRandom().randrange(2**31)
    pool = heldout()
    urls = pool if a.n <= 0 else random.Random(seed).sample(pool, min(a.n, len(pool)))
    print(f"regress-legit: gateway={BASE} sample={len(urls)}/{len(pool)} seed={seed}", flush=True)

    def one(u: str) -> dict[str, Any]:
        try:
            return check(u, a.delay)
        except Exception as exc:  # noqa: BLE001
            return {"verdict": f"error:{type(exc).__name__}", "degraded": False, "tier": None}

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(one, urls))
    counts = Counter(r["verdict"] for r in res)
    flagged = [int(r["verdict"] in ("suspicious", "dangerous")) for r in res]
    lo, hi = bootstrap_ci(flagged)
    degraded = sum(r["degraded"] for r in res)
    errors = sum(v for k, v in counts.items() if k.startswith("error:"))
    fpr = sum(flagged) / max(1, len(flagged))
    print(
        f"regress-legit: n={len(res)} {dict(counts)} degraded={degraded} errors={errors} "
        f"fpr={fpr:.4f} ci95=[{lo:.4f},{hi:.4f}] seed={seed}"
    )
    if a.out:
        Path(a.out).write_text(json.dumps({"seed": seed, "counts": counts, "fpr": fpr, "ci95": [lo, hi],
                                           "degraded": degraded, "errors": errors, "results": res}))  # fmt: skip
    return 1 if sum(flagged) or errors else 0


if __name__ == "__main__":
    sys.exit(main())
