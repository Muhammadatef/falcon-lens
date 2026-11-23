# ruff: noqa: E501
"""Message-text eval: link-free scam messages through the shipped message path (analyze_message + arbiter).

Positive = scam; a warning = verdict ``suspicious`` or ``dangerous``. Reports recall and false-alarm rate (FPR) with
Wilson 95% intervals on VAL and TEST, plus the same numbers WITHOUT ``message.scam_intent`` (the rule-only "before").
Everything is synthetic (labelled so in the artifact). Numbers are computed here, never typed.

Usage:
  uv run python -m evals.message_text.run                 # val only (development)
  uv run python -m evals.message_text.run --publish       # val + test, writes evals/results/published/message_text_<sha>_<ts>.json
Test is read only with --publish and only when splits.lock exists and verifies.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import UTC, datetime
from typing import Any

from evals.common import RESULTS_DIR, git_sha
from evals.message_text import data
from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import load_params
from falcon_core.signals.message.analyze import analyze_message

PUBLISHED = RESULTS_DIR / "published"


def wilson(k: int, n: int, z: float = 1.96) -> dict[str, float | None]:
    if n == 0:
        return {"value": None, "ci_low": None, "ci_high": None, "k": k, "n": n}
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {
        "value": round(p, 4),
        "ci_low": round(max(0.0, c - h), 4),
        "ci_high": round(min(1.0, c + h), 4),
        "k": k,
        "n": n,
    }


def verdict(text: str, with_intent: bool = True) -> str:
    ev = [
        from_signal(e)
        for e in analyze_message(text).evidence
        if with_intent or e.signal not in ("message.scam_intent", "message.script_match")
    ]
    ctx = ArbiterContext(input_type="message", params=load_params())
    return str(score_with_model(ev, None, ctx).verdict)


def evaluate(rows: list[dict[str, Any]], with_intent: bool) -> dict[str, Any]:
    scam = [r for r in rows if r["label"] == "scam"]
    legit = [r for r in rows if r["label"] != "scam"]
    vs = {r["id"]: verdict(r["text"], with_intent) != "no_warning_signs" for r in rows}
    out: dict[str, Any] = {
        "n": len(rows),
        "n_scam": len(scam),
        "n_legit": len(legit),
        "recall": wilson(sum(vs[r["id"]] for r in scam), len(scam)),
        "fpr": wilson(sum(vs[r["id"]] for r in legit), len(legit)),
        "recall_by_language": {},
        "fpr_by_language": {},
    }
    for lang in sorted({r["language"] for r in rows}):
        s = [r for r in scam if r["language"] == lang]
        lg = [r for r in legit if r["language"] == lang]
        out["recall_by_language"][lang] = wilson(sum(vs[r["id"]] for r in s), len(s))
        out["fpr_by_language"][lang] = wilson(sum(vs[r["id"]] for r in lg), len(lg))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true")
    a = ap.parse_args(argv)
    splits = ["val"]
    if a.publish:
        errs = data.check_lock()
        if errs:
            print("splits.lock check failed:", *errs, sep="\n  ", file=sys.stderr)
            return 1
        splits.append("test")
    res: dict[str, Any] = {}
    for s in splits:
        rows = data.items(s)
        res[s] = {"shipped": evaluate(rows, True), "rules_only_before": evaluate(rows, False)}
        for k in ("shipped", "rules_only_before"):
            m = res[s][k]
            print(
                f"{s:5} {k:18} recall {m['recall']['k']}/{m['recall']['n']} = {m['recall']['value']} "
                f"[{m['recall']['ci_low']}, {m['recall']['ci_high']}]  fpr {m['fpr']['k']}/{m['fpr']['n']} = {m['fpr']['value']} "
                f"[{m['fpr']['ci_low']}, {m['fpr']['ci_high']}]"
            )
    if not a.publish:
        return 0
    sha = git_sha()
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    weights = json.loads(
        (data.HERE.parents[1] / "packages/falcon_core/src/falcon_core/signals/message/intent_weights.json").read_text()
    )
    art = {
        "schema_version": 1,
        "kind": "message_text_eval",
        "synthetic": True,
        "note": "Synthetic, link-free messages (Falcon Demo Bank and generic roles). Recall/FPR with Wilson 95% intervals; "
        "small n means wide intervals. Test is evaluated once per build; report-only (not in evals/baseline.json).",
        "git_sha": sha,
        "created_at": ts,
        "dataset_hash": data.dataset_hash(),
        "intent_fit": weights["fit"],
        "intent_theta": weights["theta"],
        "metrics": {
            f"message_text.{s}.{k}.{m}": res[s][k][m]["value"]
            for s in res
            for k in ("shipped", "rules_only_before")
            for m in ("recall", "fpr")
        },
        "results": res,
    }
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    path = PUBLISHED / f"message_text_{sha[:12]}_{ts}.json"
    path.write_text(json.dumps(art, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", path)
    _ = time
    return 0


if __name__ == "__main__":
    sys.exit(main())
