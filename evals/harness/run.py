"""`make eval`: offline T1 + arbiter evaluation with bootstrap CIs, written as JSON + HTML + Prometheus textfile.

Every number in the artifact is computed here from the frozen splits; nothing is typed by hand. What cannot be
computed yet (sandbox tier, LLM tiers, injection, faithfulness, cloud and sovereign columns) is written as
``{"status": "not_evaluated", "reason": ...}``, never as a number.

Usage: ``python -m evals.harness.run [--splits val,test] [--publish] [--boot 1000] [--seed N]``

When to use it:
    After `make fit-thresholds` or any scoring change, to see how detection quality moved. Needs the
    private data on this machine (it cannot run in CI).

How to run:
    make eval                  (direct: uv run python -m evals.harness.run)
    uv run python -m evals.harness.run --publish      (also write the URL-free published summary)

Inputs:
    The hashed manifest, the private item cache, the frozen split lock and the fitted model. Options:
    --splits, --boot (bootstrap rounds), --seed, --out-dir, --publish.

Outputs / side effects:
    Writes <timestamp>.json, latest.json, <timestamp>.html, latest.html and latest.prom into
    evals/results/ (or --out-dir), and with --publish a URL-free <timestamp>.json under
    evals/results/published/. It refuses to write any file that would contain a URL. No network calls.
    scripts/readme_metrics.py later copies published numbers into README.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from evals.common import ITEMS_MANIFEST, PARAMS_YAML, RESULTS_DIR, SEED, git_sha, read_jsonl
from evals.datasets.build import CacheMismatch, Item, load_private_items, verify_private_items
from evals.harness import metrics as M
from evals.harness.message_path import evaluate_message_path
from evals.harness.report import render_html, render_prom
from evals.splits import check_rows, load_lock
from evals.train.fit import HGB_PARAMS, apply_platt, fit_platt
from evals.train.pipeline import FEATURE_GROUPS, feature_matrix, score_url
from falcon_core.scoring.params import ScoringParams, load_params
from falcon_core.scoring.t1_model import T1Model, load_t1_model
from falcon_core.signals.url.lexical import FEATURE_NAMES

SCHEMA_VERSION = 1
N_BOOT = 1000
LLM_NOT_WIRED = "LLM tiers (T3) are not wired into the offline harness yet"
NOT_EVALUATED_GLOBAL = {
    "sandbox_tier_T2": "sandbox snapshot replay (T-021) is not available to the harness yet",
    "llm_tier_T3": LLM_NOT_WIRED,
    "injection_attack_success_rate": "needs the LLM tiers and evals/redteam fixtures",
    "faithfulness": "needs the LLM tiers (reasons verifier on model output)",
    "flip_rate_3_runs": "needs the LLM tiers",
    "arabic_clarity": "needs the LLM tiers and the owner-rated calibration set",
    "cost_per_check_llm": LLM_NOT_WIRED,
}


def not_evaluated(reason: str) -> dict[str, str]:
    """The placeholder written instead of a number when something cannot be measured yet."""
    return {"status": "not_evaluated", "reason": reason}


def _pct(vals: Sequence[float], q: float) -> float | None:
    return round(float(np.percentile(vals, q)), 4) if len(vals) else None


def score_items(
    items: Sequence[Item], model: T1Model, params: ScoringParams, with_registry: bool = True
) -> dict[str, Any]:
    """Score items through the T1 classifier and arbiter; returns the per-item results as a dict."""
    p_clf = model.p_clf_many([i.url for i in items])
    t0 = time.perf_counter()
    scored = [score_url(i.url, pc, params, with_registry) for i, pc in zip(items, p_clf, strict=True)]
    wall = time.perf_counter() - t0
    return {
        "y": np.array([i.label for i in items]),
        "p": np.array([s.result.calibrated_probability for s in scored]),
        "p_clf": np.array(p_clf),
        "verdict": [s.result.verdict for s in scored],
        "fired": np.array([bool(s.result.fired_rules) for s in scored]),
        "conflict": np.array([s.brand_conflict for s in scored]),
        "latency_ms": [s.latency_ms for s in scored],
        "wall_s": wall,
    }


def _headline(y: np.ndarray, warn: np.ndarray, p: np.ndarray, n_boot: int, seed: int) -> dict[str, Any]:
    def rate(fn):  # type: ignore[no-untyped-def]
        return lambda yy, ww: fn(yy, ww.astype(bool))

    return {
        "n": int(len(y)),
        "n_phishing": int(y.sum()),
        "n_legit": int((1 - y).sum()),
        "precision": M.with_ci(rate(M.precision), y, warn, n_boot, seed),
        "recall": M.with_ci(rate(M.recall), y, warn, n_boot, seed + 1),
        "f1": M.with_ci(rate(M.f1), y, warn, n_boot, seed + 2),
        "fpr": M.with_ci(rate(M.fpr), y, warn, n_boot, seed + 3),
        "pr_auc": M.with_ci(M.pr_auc, y, p, n_boot, seed + 4),
        "ece": M.with_ci(lambda yy, pp: M.ece(yy, pp), y, p, n_boot, seed + 5),
        "reliability": M.reliability(y, p),
    }


def evaluate_split(
    name: str, items: list[Item], model: T1Model, params: ScoringParams, n_boot: int, seed: int
) -> dict[str, Any]:
    """Compute all metrics and breakdowns for one split."""
    r = score_items(items, model, params)
    y, p = r["y"], r["p"]
    verdict = np.array(r["verdict"])
    warn = verdict != "no_warning_signs"
    dang = verdict == "dangerous"
    kinds = np.array([i.kind for i in items])
    official = np.array([i.official for i in items])
    zero_day = np.array([i.zero_day for i in items])
    cats = np.array([i.category for i in items])

    out: dict[str, Any] = {
        "split": name,
        "operating_point": "warning = verdict in {suspicious, dangerous}; positive class = phishing",
        "overall": _headline(y, warn, p, n_boot, seed),
        "dangerous_only": {
            "precision": M.with_ci(lambda yy, ww: M.precision(yy, ww.astype(bool)), y, dang, n_boot, seed + 10),
            "recall": M.with_ci(lambda yy, ww: M.recall(yy, ww.astype(bool)), y, dang, n_boot, seed + 11),
            "fpr": M.with_ci(lambda yy, ww: M.fpr(yy, ww.astype(bool)), y, dang, n_boot, seed + 12),
        },
        "classifier_only": {
            "pr_auc_p_clf": M.with_ci(M.pr_auc, y, r["p_clf"], n_boot, seed + 13),
            "ece_p_clf": M.with_ci(lambda yy, pp: M.ece(yy, pp), y, r["p_clf"], n_boot, seed + 14),
        },
    }
    for kind in ("real", "synthetic"):
        m = kinds == kind
        out[kind] = (
            _headline(y[m], warn[m], p[m], n_boot, seed + 20)
            if m.any() and y[m].sum() > 0
            else not_evaluated(
                f"no {kind} items with phishing labels in this split" if not m.any() else f"no {kind} phishing items"
            )
        )
    n_off = int(official.sum())
    off_fd = int((dang & official).sum())
    out["verified_official"] = {
        "n": n_off,
        "false_dangerous": off_fd,
        "false_warning": int((warn & official).sum()),
        "false_dangerous_upper_95": round(3 / n_off, 4) if n_off and off_fd == 0 else None,
        "note": "upper bound is the rule of three; H3 (verified-official cap) is applied by the arbiter",
    }
    raw = score_items([i for i in items if i.official], model, params, with_registry=False) if n_off else None
    out["verified_official"]["false_dangerous_without_H3"] = (
        int((np.array(raw["verdict"]) == "dangerous").sum()) if raw else 0
    )
    if zero_day.any():
        zm = zero_day
        out["zero_day"] = {
            "n": int(zm.sum()),
            "recall_system": M.with_ci(lambda yy, ww: float(np.mean(ww)), y[zm], warn[zm], n_boot, seed + 30),
            "recall_blocklist_only_baseline": {"value": 0.0, "status": "by_construction"},
            "baseline_note": "zero-day items are by definition on no enabled blocklist, so the baseline recall is 0",
        }
    else:
        out["zero_day"] = not_evaluated(
            "0 zero-day items: every OpenPhish row is listed on OpenPhish by definition and no Falcon Demo Bank "
            "fixture pages or marked items exist yet (EVALS target >= 40)"
        )
    by_cat: dict[str, Any] = {}
    for c in sorted(set(cats[y == 0])):
        m = (cats == c) & (y == 0)
        by_cat[str(c)] = {"n": int(m.sum()), "false_warning_rate": round(float(warn[m].mean()), 4)}
    out["legit_by_category"] = by_cat
    out["credential_form_pages"] = credential_form_pages(items, r["p_clf"], params, n_boot, seed + 300)
    out["message_path"] = evaluate_message_path(items, r["p_clf"], params, n_boot, seed + 200)
    lat = r["latency_ms"]
    out["latency_ms"] = {
        "T0_mirror": not_evaluated("local mirror tier is not wired into the offline harness"),
        "T1": {"p50": _pct(lat, 50), "p95": _pct(lat, 95), "n": len(lat), "includes": "url signals + arbiter, offline"},
        "T2": not_evaluated(NOT_EVALUATED_GLOBAL["sandbox_tier_T2"]),
        "T3": not_evaluated(LLM_NOT_WIRED),
    }
    from evals.train.fit import Thresholds, t3_share

    th = Thresholds(params.tau_low, params.tau_high, params.eps_low, params.eps_high, [])
    out["llm"] = {
        "share_reaching_llm": not_evaluated(LLM_NOT_WIRED),
        "t3_escalation_share_by_thresholds": round(t3_share(p, r["p_clf"], r["conflict"], th, r["fired"]), 4),
        "t3_budget": 0.15,
    }
    out["cost_per_check_usd"] = {
        "T1_offline": {"value": 0.0, "status": "by_construction", "reason": "T1 makes no paid calls; not measured"},
        "llm": not_evaluated(LLM_NOT_WIRED),
    }
    out["routes"] = {
        "cloud": not_evaluated(LLM_NOT_WIRED),
        "sovereign": not_evaluated(LLM_NOT_WIRED),
        "note": "T1 and the arbiter do not use an LLM, so the numbers above hold for both routes",
    }
    return out


def credential_form_pages(
    items: Sequence[Item], p_clf: Sequence[float], params: ScoringParams, n_boot: int, seed: int
) -> dict[str, Any]:
    """`dangerous`-band recall for phishing pages that show a password form (T2 evidence `page.cred_form`), and the
    legit `dangerous` rate when every legit page is assumed to show one (worst case). SYNTHETIC scenario: the
    credential form is added to every item; no page was fetched."""
    from falcon_core.cascade.evidence import make_evidence

    form = make_evidence("page.cred_form", "page", {"present": True}, tier="T2", source="computed")
    y = np.array([i.label for i in items])
    dang = np.array(
        [
            score_url(i.url, float(pc), params, extra_evidence=[form]).result.verdict == "dangerous"
            for i, pc in zip(items, p_clf, strict=True)
        ]
    )
    return {
        "kind": "synthetic_scenario",
        "note": "page.cred_form added to every item; the model-cap rule applies (params.model_cap)",
        "dangerous_recall": M.with_ci(lambda yy, ww: M.recall(yy, ww.astype(bool)), y, dang, n_boot, seed),
        "legit_dangerous_rate": M.with_ci(lambda yy, ww: M.fpr(yy, ww.astype(bool)), y, dang, n_boot, seed + 1),
        "dangerous_phishing": f"{int(dang[y == 1].sum())}/{int((y == 1).sum())}",
        "dangerous_legit": f"{int(dang[y == 0].sum())}/{int((y == 0).sum())}",
    }


def ablation(train: list[Item], val: list[Item], seed: int) -> dict[str, Any]:
    """Drop one feature group at a time (retrain on train, Platt on val); report validation PR-AUC and recall at
    the operating point (smallest cut with legit FPR <= 2% on validation). Validation only."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    xt, xv = feature_matrix([i.url for i in train]), feature_matrix([i.url for i in val])
    yt, yv = np.array([i.label for i in train]), np.array([i.label for i in val])

    def run(drop: tuple[str, ...]) -> dict[str, Any]:
        keep = [k for k, n in enumerate(FEATURE_NAMES) if n not in drop]
        m = HistGradientBoostingClassifier(random_state=seed, **HGB_PARAMS).fit(xt[:, keep], yt)  # type: ignore[arg-type]
        raw = m.predict_proba(xv[:, keep])[:, 1]
        pc = apply_platt(fit_platt(raw, yv), raw)
        legit = np.sort(pc[yv == 0])
        cut = legit[int(np.ceil(0.98 * len(legit))) - 1] if len(legit) else 1.0
        warn = pc > cut
        return {
            "pr_auc": M._clean(M.pr_auc(yv, pc)),
            "recall_at_fpr_le_2pct": M._clean(M.recall(yv, warn)),
            "fpr": M._clean(M.fpr(yv, warn)),
        }

    out = {"all_features": run(())}
    for g, cols in FEATURE_GROUPS.items():
        out[f"minus_{g}"] = run(cols)
    out["note"] = (
        "groups are subsets of the url signal family (the only family wired offline); no registry/H3 here: see "
        "verified_official.false_dangerous_without_H3"
    )
    return out


def run_eval(splits: Sequence[str], n_boot: int, seed: int) -> dict[str, Any]:
    """Evaluate the requested splits and return the full artifact dict."""
    rows = read_jsonl(ITEMS_MANIFEST)
    lock = load_lock()
    errs = check_rows(rows, lock)
    if errs or lock is None:
        raise SystemExit("split check failed, refusing to evaluate: " + "; ".join(errs))
    items = load_private_items()
    try:
        verify_private_items(items, rows)
    except CacheMismatch as exc:
        raise SystemExit(f"refusing to evaluate: {exc}") from exc
    model = load_t1_model()
    params = load_params(PARAMS_YAML)
    meta = model.meta
    if meta.get("dataset_hash") != lock["dataset_hash"]:
        raise SystemExit("the T1 model was fitted on a different dataset hash: rerun `make fit-thresholds`")
    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha(),
        "dataset_hash": lock["dataset_hash"],
        "splits_lock": {k: lock[k] for k in ("test_sha256", "temporal_cut", "counts", "seed")},
        "temporal_cut": lock["temporal_cut"],
        "temporal_cut_note": (
            "split is a seeded domain-grouped random split: fewer than 3 collection polls exist, so a temporal cut "
            "is not yet possible"
            if not lock["temporal_cut"]
            else "every test phishing first_seen is later than train"
        ),
        "model_ids": {
            "t1": {k: meta[k] for k in ("model_id", "model_sha256", "sklearn_version", "git_sha", "fit_date")},
            "llm_cloud": "not_evaluated",
            "llm_sovereign": "not_evaluated",
        },
        "thresholds": {
            "tau_low": params.tau_low,
            "tau_high": params.tau_high,
            "eps_low": params.eps_low,
            "eps_high": params.eps_high,
            "fit_source": "validation split only (make fit-thresholds)",
        },
        "seeds": {"split": lock["seed"], "model": meta["seed"], "bootstrap": seed, "n_bootstrap": n_boot},
        "data_notes": {
            "phishing": "OpenPhish community feed, real; all rows share one first_seen (single poll)",
            "legit": "evals/datasets/legit_urls.csv: real; includes verified-official and hard-negative pages",
            "caveat": (
                "legit items are mostly site roots or fixed pages and phishing items are feed URLs, so URL-shape "
                "features may separate the classes more easily than they would on live traffic; treat the numbers "
                "as an offline lexical baseline, not a field estimate"
            ),
            "synthetic": "no synthetic URL items in this dataset; synthetic reported not_evaluated",
        },
        "not_evaluated": NOT_EVALUATED_GLOBAL,
        "splits": {},
    }
    by_split: dict[str, list[Item]] = defaultdict(list)
    for i in items:
        by_split[i.split].append(i)
    for s in splits:
        out["splits"][s] = evaluate_split(s, by_split[s], model, params, n_boot, seed)
    if "val" in splits:
        out["splits"]["val"]["ablation"] = ablation(by_split["train"], by_split["val"], int(meta["seed"]))
    return out


_URL_RE = re.compile(r"(?i)\b(?:https?|hxxps?|ftp)://|\bwww\.")


def assert_url_free(doc: dict[str, Any]) -> None:
    """Abort if the artifact contains anything that looks like a URL."""
    text = json.dumps(doc)
    if _URL_RE.search(text):
        raise SystemExit("published artifact would contain a URL; refusing")


def publish_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """Compact, URL-free summary for evals/results/published/ (feeds the README block via readme_metrics)."""
    metrics: dict[str, Any] = {}
    for split, s in doc["splits"].items():
        for name in ("precision", "recall", "f1", "fpr", "pr_auc", "ece"):
            m = s["overall"][name]
            metrics[f"{split}.{name}"] = m["value"]
            metrics[f"{split}.{name}_ci95"] = [m["ci_low"], m["ci_high"]]
        mp = s["message_path"]
        for name in ("recall", "fpr", "dangerous_recall"):
            metrics[f"{split}.message_path.{name}"] = mp[name]["value"]
            metrics[f"{split}.message_path.{name}_ci95"] = [mp[name]["ci_low"], mp[name]["ci_high"]]
        metrics[f"{split}.message_path.n"] = mp["n_messages"]
        metrics[f"{split}.official_false_dangerous"] = s["verified_official"]["false_dangerous"]
        metrics[f"{split}.n"] = s["overall"]["n"]
    keys = ("schema_version", "created_at", "git_sha", "dataset_hash", "temporal_cut", "seeds", "model_ids")
    return {
        **{k: doc[k] for k in keys},
        "thresholds": doc["thresholds"],
        "metrics": metrics,
        "not_evaluated": sorted(doc["not_evaluated"]) + ["zero_day", "synthetic", "cloud_route", "sovereign_route"],
        "scope": "offline T1 + arbiter on URLs; real data only; temporal_cut false (single poll)",
    }


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation and write the result files (see module docstring)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--splits", default="val,test")
    ap.add_argument("--boot", type=int, default=N_BOOT)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--publish", action="store_true", help="also copy a URL-free JSON to evals/results/published/")
    ap.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = ap.parse_args(argv)
    doc = run_eval(args.splits.split(","), args.boot, args.seed)
    assert_url_free(doc)
    ts = doc["created_at"].replace("-", "").replace(":", "")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    for name in (f"{ts}.json", "latest.json"):
        (args.out_dir / name).write_text(text, encoding="utf-8")
    html = render_html(doc)
    (args.out_dir / f"{ts}.html").write_text(html, encoding="utf-8")
    (args.out_dir / "latest.html").write_text(html, encoding="utf-8")
    (args.out_dir / "latest.prom").write_text(render_prom(doc), encoding="utf-8")
    if args.publish:
        pub = args.out_dir / "published"
        pub.mkdir(exist_ok=True)
        pdoc = publish_doc(doc)
        assert_url_free(pdoc)
        (pub / f"{ts}.json").write_text(json.dumps(pdoc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    v = doc["splits"].get("val", {}).get("overall")
    if v:
        print(f"val recall={v['recall']['value']} fpr={v['fpr']['value']} pr_auc={v['pr_auc']['value']}")
    print(f"wrote {args.out_dir / (ts + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
