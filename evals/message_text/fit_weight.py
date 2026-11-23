# ruff: noqa: E501
"""Fit the arbiter weight of ``message.scam_intent`` on VAL only (same procedure as the L1 D2 model-cap fit).

Objective: maximise VAL recall on scam messages subject to VAL legitimate false-alarm rate <= 2%; ties go to the
smallest weight. The shipped message path is scored (rules, intent, floors, script_match, arbiter). Test is never read.
Writes the weight into params.yaml and the fit artifact evals/results/published/fits/message_scam_intent_weight_fit.json.

Usage: ``uv run python -m evals.message_text.fit_weight``
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys

from evals.common import PARAMS_YAML, RESULTS_DIR, git_sha
from evals.message_text import data
from falcon_core.cascade.evidence import from_signal
from falcon_core.scoring.arbiter import ArbiterContext
from falcon_core.scoring.model_cap import score_with_model
from falcon_core.scoring.params import load_params
from falcon_core.signals.message.analyze import analyze_message

GRID = [round(0.5 * i, 1) for i in range(0, 21)]  # 0 .. 10
FPR_MAX = 0.02


def main() -> int:
    params = load_params()
    rows = data.items("val")
    evid = {r["id"]: [from_signal(e) for e in analyze_message(r["text"]).evidence] for r in rows}
    scam = [r for r in rows if r["label"] == "scam"]
    legit = [r for r in rows if r["label"] != "scam"]
    table = []
    for w in GRID:
        p = dataclasses.replace(params, weights={**params.weights, "message.scam_intent": w})
        ctx = ArbiterContext(input_type="message", params=p)
        warn = {r["id"]: score_with_model(evid[r["id"]], None, ctx).verdict != "no_warning_signs" for r in rows}
        rec = sum(warn[r["id"]] for r in scam) / len(scam)
        fpr = sum(warn[r["id"]] for r in legit) / len(legit)
        table.append({"weight": w, "val_recall": round(rec, 4), "val_fpr": round(fpr, 4)})
    ok = [t for t in table if t["val_fpr"] <= FPR_MAX]
    best = max(ok, key=lambda t: (t["val_recall"], -t["weight"]))
    text = PARAMS_YAML.read_text(encoding="utf-8")
    text = re.sub(
        r"(  message\.scam_intent: )[0-9.]+( *#.*)?",
        rf"\g<1>{best['weight']}  # fitted on val: evals/message_text/fit_weight.py",
        text,
    )
    PARAMS_YAML.write_text(text, encoding="utf-8")
    art = {
        "kind": "message_scam_intent_weight_fit",
        "label": "synthetic, single-author, pending audit",
        "procedure": "maximise val recall s.t. val legit FPR <= 2%; ties to the smallest weight (as L1 D2 model_cap fit)",
        "git_sha": git_sha(),
        "dataset_hash": data.dataset_hash(),
        "n_val_scam": len(scam),
        "n_val_legit": len(legit),
        "chosen": best,
        "grid": table,
    }
    out = RESULTS_DIR / "published" / "fits" / "message_scam_intent_weight_fit.json"
    out.write_text(json.dumps(art, indent=1) + "\n", encoding="utf-8")
    print("chosen", best)
    return 0


if __name__ == "__main__":
    sys.exit(main())
