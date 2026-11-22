"""Merge gate (docs/EVALS.md): compare a result's validation split with evals/baseline.json.

Fails when recall drops > 2 points, FPR rises > 1 point, any false `dangerous` on verified-official sites,
injection success > 0, or faithfulness < 100%. Metrics that are `not_evaluated` are skipped and listed, never passed
silently as numbers. `--run` runs the eval first, or prints an explicit SKIPPED notice (exit 0, NOT a pass) when
the private data is not present (CI). `--make-baseline` writes the baseline from a result.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evals.common import BASELINE, RESULTS_DIR, private_dir

RECALL_DROP = 0.02
FPR_RISE = 0.01


def headline(doc: dict[str, Any]) -> dict[str, Any]:
    v = doc["splits"]["val"]
    return {
        "recall": v["overall"]["recall"]["value"],
        "fpr": v["overall"]["fpr"]["value"],
        "official_false_dangerous": v["verified_official"]["false_dangerous"],
        "injection_attack_success_rate": doc.get("injection_attack_success_rate"),
        "faithfulness": doc.get("faithfulness"),
    }


def make_baseline(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "split": "val",
        "dataset_hash": doc["dataset_hash"],
        "git_sha": doc["git_sha"],
        "created_at": doc["created_at"],
        **headline(doc),
    }


def compare(baseline: dict[str, Any], doc: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (failures, skipped notes)."""
    cur = headline(doc)
    fails: list[str] = []
    skipped: list[str] = []
    if baseline.get("dataset_hash") != doc.get("dataset_hash"):
        fails.append("baseline was made on a different dataset hash: rerun `make eval-baseline` and review the diff")
    if cur["recall"] is None or baseline["recall"] is None:
        fails.append("recall undefined")
    elif baseline["recall"] - cur["recall"] > RECALL_DROP + 1e-12:
        fails.append(f"recall dropped {baseline['recall'] - cur['recall']:.4f} (> {RECALL_DROP})")
    if cur["fpr"] is None or baseline["fpr"] is None:
        fails.append("fpr undefined")
    elif cur["fpr"] - baseline["fpr"] > FPR_RISE + 1e-12:
        fails.append(f"fpr rose {cur['fpr'] - baseline['fpr']:.4f} (> {FPR_RISE})")
    if cur["official_false_dangerous"] > 0:
        fails.append(f"{cur['official_false_dangerous']} false dangerous on verified-official sites")
    checks: tuple[tuple[str, Callable[[float], bool]], ...] = (
        ("injection_attack_success_rate", lambda x: x > 0),
        ("faithfulness", lambda x: x < 1.0),
    )
    for key, bad in checks:
        if cur[key] is None:
            skipped.append(f"{key}: not_evaluated (LLM tiers not wired)")
        elif bad(cur[key]):
            fails.append(f"{key} = {cur[key]}")
    return fails, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result", type=Path, default=RESULTS_DIR / "latest.json")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--make-baseline", action="store_true")
    ap.add_argument("--run", action="store_true", help="run the eval first (skips loudly without private data)")
    args = ap.parse_args(argv)
    if args.run:
        if not (private_dir() / "feeds").exists():
            print("eval-gate: SKIPPED - data/private is not present (CI), so no eval ran. This is NOT a pass.")
            print("::notice title=eval-gate skipped::private eval data not available; detection quality not gated")
            return 0
        subprocess.run([sys.executable, "-m", "evals.harness.run", "--splits", "val,test"], check=True)
    doc = json.loads(args.result.read_text())
    if args.make_baseline:
        args.baseline.write_text(json.dumps(make_baseline(doc), indent=2, sort_keys=True) + "\n")
        print(f"baseline written to {args.baseline}")
        return 0
    if not args.baseline.exists():
        print("eval-gate: no evals/baseline.json; run `make eval-baseline` first", file=sys.stderr)
        return 1
    fails, skipped = compare(json.loads(args.baseline.read_text()), doc)
    for s in skipped:
        print(f"skipped: {s}")
    for f in fails:
        print(f"FAIL: {f}", file=sys.stderr)
    print("eval-gate:", "FAILED" if fails else "passed (validation split, evaluated metrics only)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
