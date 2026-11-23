"""Fit the ``message.scam_intent`` logistic weights on TRAIN only; pick C and theta on VAL only. Never reads test.

Usage: ``uv run python -m evals.message_text.fit``  (writes packages/falcon_core/.../message/intent_weights.json)

theta = the lowest probability (>= THETA_MIN) whose VAL false-alarm rate is 0 on the legitimate items of TRAIN and VAL
combined; if no such value exists, the one with the lowest false-alarm rate. THETA_MIN keeps ``W * p`` above the
``suspicious`` boundary given the arbiter weight W in params.yaml (see docs/SCORING.md).
"""

from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression

from evals.message_text.data import dataset_hash, items
from falcon_core.signals.message.intent import FEATURE_ORDER, WEIGHTS_PATH, extract_features

THETA_MIN = 0.65
C_GRID = (0.1, 0.3, 1.0, 3.0, 10.0)


def matrix(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[extract_features(r["text"]).get(k, 0) for k in FEATURE_ORDER] for r in rows], dtype=float)
    y = np.array([1 if r["label"] == "scam" else 0 for r in rows])
    return x, y


def main() -> int:
    tr, va = items("train"), items("val")
    xt, yt = matrix(tr)
    xv, yv = matrix(va)
    best = None
    for c in C_GRID:
        m = LogisticRegression(C=c, max_iter=2000, class_weight="balanced").fit(xt, yt)
        p = m.predict_proba(xv)[:, 1]
        ll = -float(np.mean(yv * np.log(p + 1e-9) + (1 - yv) * np.log(1 - p + 1e-9)))
        if best is None or ll < best[0]:
            best = (ll, c, m)
    if best is None:
        raise SystemExit("no model fitted")
    ll, c, m = best
    # theta from legit items of train+val scores, scams of val for recall
    xa, ya = np.vstack([xt, xv]), np.concatenate([yt, yv])
    pa = m.predict_proba(xa)[:, 1]
    legit = np.sort(pa[ya == 0])
    theta = max(THETA_MIN, float(legit[-1]) + 1e-6 if len(legit) else THETA_MIN)
    theta = min(theta, 0.97)
    weights = {k: round(float(w), 4) for k, w in zip(FEATURE_ORDER, m.coef_[0], strict=True) if abs(w) > 1e-6}
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"
    out = {
        "kind": "logistic",
        "bias": round(float(m.intercept_[0]), 4),
        "weights": weights,
        "theta": round(theta, 4),
        "fit": {
            "split": "train (weights), val (C, theta)",
            "C": c,
            "val_logloss": round(ll, 4),
            "n_train": len(tr),
            "n_val": len(va),
            "dataset_hash": dataset_hash(),
            "git_sha": sha,
            "class_weight": "balanced",
            "note": "the fit never read test; test was read three times for reporting only (see test_read)",
        },
    }
    WEIGHTS_PATH.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"C={c} theta={out['theta']} bias={out['bias']} n_train={len(tr)} n_val={len(va)}")
    print(json.dumps(weights, indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
