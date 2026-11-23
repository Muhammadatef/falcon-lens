"""`make fit-thresholds`: train the T1 classifier, calibrate it, fit the bands and cascade exits (SCORING §1).

* HistGradientBoostingClassifier is trained on the TRAIN split;
* Platt calibration, tau_low/tau_high and eps_low/eps_high are fitted on the VALIDATION split only;
* this module refuses to read the TEST split (``load_items`` raises); the eval harness is the only reader of test;
* two runs on the same dataset and seed write byte-identical params.yaml, model metadata and model file.

Fit rules (docs/SCORING.md §1.5/§1.6, docs/EVALS.md):
* tau_low: smallest cut keeping validation FPR (share of legit items with any warning) <= 2%, within [0.10, 0.90];
* tau_high: smallest cut >= tau_low + 0.05 with validation `dangerous` rate on legit <= 1% (assumption, DECISIONS.md)
  and zero `dangerous` on verified-official items, capped at h1_p_floor (0.95);
* eps_low: below every validation phishing p_clf that has no brand conflict (no recall loss), capped at tau_low / 2;
* eps_high: above every validation legit p_clf (no false `dangerous` exit at T1), at least tau_high + 0.05, <= 0.99;
* share of validation items that would reach T3 is computed and reported against the 15% budget, not forced.

When to use it:
    After `evals.datasets.build` produced a new item set, or when the T1 features change.

How to run:
    make fit-thresholds        (runs the dataset build, then this)
    uv run python -m evals.train.fit [--seed N] [--date YYYY-MM-DD] [--dry-run]

Inputs:
    The hashed manifest, the private item cache and the split lock (checked for integrity first).
    --dry-run prints the fitted thresholds and writes nothing.

Outputs / side effects:
    Without --dry-run it writes the model and its metadata under
    packages/falcon_core/src/falcon_core/scoring/model/ and updates the fitted values in
    packages/falcon_core/src/falcon_core/scoring/params.yaml. No network calls.

Safety notes:
    It cannot read the test split (it raises); only the eval harness may. Review the params.yaml diff in
    the PR because it changes detection behaviour.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from evals.common import ITEMS_MANIFEST, MODEL_DIR, PARAMS_YAML, RESULTS_DIR, SEED, git_sha, read_jsonl, sha256_hex
from evals.datasets.build import CacheMismatch, Item, load_private_items, verify_private_items
from evals.splits import check_rows, load_lock
from evals.splits import dataset_hash as manifest_dataset_hash
from evals.train.pipeline import feature_matrix, score_url
from falcon_core.scoring.params import load_params, params_from_mapping
from falcon_core.signals.url.lexical import FEATURE_NAMES

FPR_TARGET = 0.02
DANGEROUS_FPR_TARGET = 0.01
TAU_LOW_MIN, TAU_LOW_MAX = 0.10, 0.90
T3_BUDGET = 0.15
MODEL_FILE = "t1_hgb.joblib"
META_FILE = "t1_hgb.meta.json"


class SplitIntegrityError(RuntimeError):
    """The data to be fitted on does not match the frozen, verified split."""


class TestSplitAccess(RuntimeError):
    """Raised when fitting code asks for the frozen test split."""

    __test__ = False


def load_items(
    splits: Sequence[str],
    items: list[Item] | None = None,
    rows: list[dict[str, object]] | None = None,
    lock: dict[str, object] | None = None,
) -> list[Item]:
    """Items of the requested splits, after checking the private cache against the public manifest and the lock.

    Refuses the test split, a manifest that fails the split invariants or the lock, and any cached item whose
    split/label/domain differs from the manifest (a relabelled-cache attack that would put test items in train).
    """
    if "test" in splits:
        raise TestSplitAccess("fit-thresholds must never read the test split (docs/EVALS.md: never tune on test)")
    rows = read_jsonl(ITEMS_MANIFEST) if rows is None else rows
    lock = load_lock() if lock is None else lock
    errs = check_rows(rows, lock)
    if errs:
        raise SplitIntegrityError("; ".join(errs))
    cache = load_private_items() if items is None else items
    try:
        verify_private_items(cache, rows)
    except CacheMismatch as exc:
        raise SplitIntegrityError(str(exc)) from exc
    test_ids = {str(r["item_id"]) for r in rows if r["split"] == "test"}
    out = [i for i in cache if i.split in splits]
    if any(i.item_id in test_ids for i in out):
        raise SplitIntegrityError("a test item appears in the requested splits")
    return out


def items_hash(items: Sequence[Item]) -> str:
    """Hash of the item ids used for a fit (recorded in the model metadata)."""
    return sha256_hex("\n".join(sorted(f"{i.item_id}:{i.label}:{i.split}" for i in items)))


HGB_PARAMS = {
    "max_iter": 150,
    "learning_rate": 0.08,
    "max_leaf_nodes": 8,
    "min_samples_leaf": 10,
    "l2_regularization": 1.0,
    "early_stopping": False,
}


def train_model(train: Sequence[Item], seed: int) -> object:
    """Train the HistGradientBoostingClassifier on the given items."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    x = feature_matrix([i.url for i in train])
    y = np.array([i.label for i in train])
    return HistGradientBoostingClassifier(random_state=seed, **HGB_PARAMS).fit(x, y)  # type: ignore[arg-type]


def fit_platt(raw: np.ndarray, y: np.ndarray) -> object:
    """Platt scaling on logit(raw). Isotonic was tried first and gave 4 distinct probabilities on 144 validation
    items (too coarse to place two thresholds); sigmoid keeps the ranking and is smooth (DECISIONS.md)."""
    from sklearn.linear_model import LogisticRegression

    r = np.clip(raw, 1e-6, 1 - 1e-6)
    return LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000).fit(np.log(r / (1 - r)).reshape(-1, 1), y)


def apply_platt(platt: object, raw: np.ndarray) -> np.ndarray:
    """Apply the Platt calibration to raw model scores."""
    r = np.clip(raw, 1e-6, 1 - 1e-6)
    return np.asarray(platt.predict_proba(np.log(r / (1 - r)).reshape(-1, 1))[:, 1], dtype=float)  # type: ignore[attr-defined]


def _mid(candidates: list[float], chosen: float) -> float:
    lower = [c for c in candidates if c < chosen]
    return round((chosen + (max(lower) if lower else 0.0)) / 2, 4)


@dataclass
class Thresholds:
    """The fitted band edges tau_low, tau_high, eps_low, eps_high plus notes."""

    tau_low: float
    tau_high: float
    eps_low: float
    eps_high: float
    notes: list[str]


def fit_bands(
    p: np.ndarray, y: np.ndarray, official: np.ndarray, p_clf: np.ndarray, brand_conflict: np.ndarray, h1_floor: float
) -> Thresholds:
    """Pure function of validation arrays (arbiter p, label, official mask, p_clf, brand-conflict mask)."""
    notes: list[str] = []
    legit = y == 0
    n_legit = int(legit.sum())
    cands = sorted({float(v) for v in p} | {TAU_LOW_MIN})

    def legit_rate(t: float) -> float:
        return float(((p >= t) & legit).sum()) / max(n_legit, 1)

    ok_low = [t for t in cands if TAU_LOW_MIN <= t <= TAU_LOW_MAX and legit_rate(t) <= FPR_TARGET]
    if ok_low:
        tau_low = _mid(cands, min(ok_low)) if min(ok_low) > TAU_LOW_MIN else TAU_LOW_MIN
    else:
        tau_low = TAU_LOW_MAX
        notes.append("tau_low: FPR target not reachable inside [0.10, 0.90]; capped at 0.90")
    tau_low = max(TAU_LOW_MIN, min(tau_low, TAU_LOW_MAX))

    def ok_high(t: float) -> bool:
        return t >= tau_low + 0.05 and legit_rate(t) <= DANGEROUS_FPR_TARGET and not bool(((p >= t) & official).any())

    highs = [t for t in cands if ok_high(t)]
    if highs and min(highs) <= h1_floor:
        tau_high = _mid(cands, min(highs))
        tau_high = max(tau_high, round(tau_low + 0.05, 4))
    else:
        tau_high = h1_floor
        notes.append("tau_high: dangerous-FPR target not reachable at or below h1_p_floor; set to h1_p_floor")
    tau_high = min(tau_high, h1_floor)

    phish_free = (y == 1) & ~brand_conflict
    eps_low = float(p_clf[phish_free].min()) if phish_free.any() else 0.0
    eps_low = math.floor(min(eps_low, tau_low / 2) * 1e4) / 1e4
    eps_low = max(eps_low, 0.001)
    top_legit = float(p_clf[legit].max()) if n_legit else 0.0
    eps_high = min(0.99, max(tau_high + 0.05, math.ceil(top_legit * 1e4) / 1e4 + 1e-4))
    eps_high = round(eps_high, 4)
    return Thresholds(tau_low, tau_high, eps_low, eps_high, notes)


CAP_MARGINS = tuple(round(0.5 * k, 2) for k in range(0, 7))  # 0 .. 3.0 log-odds under tau_high
CAP_STRONG = tuple(round(0.5 * k, 2) for k in range(0, 11))  # 0 .. 5.0 log-odds of corroboration


@dataclass
class ModelCapFit:
    """Fitted ``model_cap`` values with the validation numbers they were chosen on."""

    margin: float
    strong_adj: float
    recall_form: float  # dangerous-band recall on validation phishing with a credential form
    fpr_form: float  # dangerous rate on validation legit with a credential form (worst case: every legit has one)
    recall_url_only: float
    fpr_url_only: float
    n_phishing: int
    n_legit: int
    notes: list[str]


def fit_model_cap(val: Sequence[Item], p_clf: np.ndarray, params: object) -> ModelCapFit:
    """Choose (margin, strong_adj) on VALIDATION only: maximise `dangerous`-band recall on phishing pages that show a
    credential form, subject to the legit `dangerous` rate staying within DANGEROUS_FPR_TARGET for URL-only checks and
    within FPR_TARGET when every legit page is assumed to show a credential form (the worst case).
    Ties: URL-only recall, then the smaller constants (least intervention)."""
    import dataclasses

    from evals.common import registrable_domain
    from evals.train.pipeline import registry_evidence, t1_evidence, verified_domains
    from falcon_core.cascade.evidence import make_evidence
    from falcon_core.scoring.arbiter import ArbiterContext
    from falcon_core.scoring.model_cap import score_with_model

    form = make_evidence(
        "page.cred_form", "page", {"present": True, "field_kinds": ["password"]}, tier="T2", source="computed"
    )
    base = []
    for i in val:
        dom = registrable_domain(i.url)
        base.append(([*t1_evidence(i.url), *registry_evidence(dom)], dom))
    y = np.array([i.label for i in val])
    vd = verified_domains()

    def rates(margin: float, adj: float, with_form: bool) -> tuple[float, float]:
        prm = dataclasses.replace(params, model_only_margin=margin, strong_evidence_adj=adj)  # type: ignore[type-var]
        dang = []
        for (ev, dom), pc in zip(base, p_clf, strict=True):
            ctx = ArbiterContext(input_type="url", registrable_domain=dom, verified_domains=vd, params=prm)
            res = score_with_model([*ev, form] if with_form else ev, float(pc), ctx)
            dang.append(res.verdict == "dangerous")
        d = np.array(dang)
        rec = float(d[y == 1].mean()) if (y == 1).any() else 0.0
        fp = float(d[y == 0].mean()) if (y == 0).any() else 0.0
        return rec, fp

    best: tuple[tuple[float, float, float, float], ModelCapFit] | None = None
    notes: list[str] = []
    for m in CAP_MARGINS:
        for a in CAP_STRONG:
            rf, ff = rates(m, a, True)
            ru, fu = rates(m, a, False)
            if ff > FPR_TARGET or fu > DANGEROUS_FPR_TARGET:
                continue
            key = (rf, ru, -m, -a)
            cand = ModelCapFit(m, a, rf, ff, ru, fu, int(y.sum()), int((1 - y).sum()), notes)
            if best is None or key > best[0]:
                best = (key, cand)
    if best is None:
        notes.append("no (margin, strong_adj) met the dangerous-FPR target; most conservative values used")
        rf, ff = rates(CAP_MARGINS[-1], CAP_STRONG[-1], True)
        ru, fu = rates(CAP_MARGINS[-1], CAP_STRONG[-1], False)
        return ModelCapFit(CAP_MARGINS[-1], CAP_STRONG[-1], rf, ff, ru, fu, int(y.sum()), int((1 - y).sum()), notes)
    return best[1]


def t3_share(p: np.ndarray, p_clf: np.ndarray, brand_conflict: np.ndarray, th: Thresholds, fired: np.ndarray) -> float:
    """Share that would reach T3: not exited at T1, not exited at T2 (SCORING §1.6)."""
    t1_exit = ((p_clf < th.eps_low) | (p_clf > th.eps_high)) & ~brand_conflict
    t2_exit = fired | (p < th.tau_low - 0.10) | (p > th.tau_high + 0.05)
    return float((~t1_exit & ~t2_exit).sum()) / max(len(p), 1)


def render_params(text: str, th: Thresholds, meta: dict[str, object], cap: ModelCapFit | None = None) -> str:
    """Rewrite only the fitted lines of params.yaml; everything else (weights, rules) is preserved verbatim."""
    header = (
        "# FITTED by `make fit-thresholds` (builder-evals) on the validation split only; do not hand-tune.\n"
        "# Fitted: bands (tau_*), cascade exits (eps_*) and the T1 classifier (scoring/model/).\n"
        "# NOT fitted: the evidence weights, hard-rule values and message-rule caps below remain the SCORING.md\n"
        "# draft values, as do the cascade t2 margins and the draft_classifier fallback intercept.\n"
    )
    lines = text.splitlines()
    out: list[str] = []
    skip_fit = False
    in_header = True
    i = 0
    while i < len(lines):
        ln = lines[i]
        if in_header and ln.startswith("#"):
            i += 1
            continue
        in_header = False
        if ln.startswith("draft:"):
            out.append("draft: false  # thresholds fitted; weights are still the SCORING.md draft values")
        elif ln.startswith("fit:"):
            out.append("fit:")
            for k, v in meta.items():
                out.append(f"  {k}: {json.dumps(v)}")
            skip_fit = True
        elif skip_fit and ln.startswith("  "):
            pass
        else:
            skip_fit = False
            ln = re.sub(r"^(  tau_high:)\s*[\d.]+", rf"\g<1> {th.tau_high}", ln)
            ln = re.sub(r"^(  tau_low:)\s*[\d.]+", rf"\g<1> {th.tau_low}", ln)
            ln = re.sub(r"^(  eps_low:)\s*[\d.]+\s*(#.*)?$", rf"\g<1> {th.eps_low}", ln)
            ln = re.sub(r"^(  eps_high:)\s*[\d.]+\s*(#.*)?$", rf"\g<1> {th.eps_high}", ln)
            out.append(ln)
        i += 1
    body = "\n".join(out) + "\n"
    if cap is not None:
        body = re.sub(r"(?m)^(?:#.*\n)*model_cap:\n(?:  .*\n)+\n?", "", body)
        block = (
            "# Fitted on VALIDATION only by `make fit-thresholds` (evals/results/published/fits/model_cap_fit.json):\n"
            "# the fitted T1 classifier alone never produces `dangerous`. margin = log-odds the model probability is\n"
            "# capped under tau_high; strong_adj = non-url risk evidence (log-odds) needed for `dangerous`\n"
            "# without a hard rule.\n"
            f"model_cap:\n  margin: {cap.margin}\n  strong_adj: {cap.strong_adj}\n\n"
        )
        body = body.replace("logit_clip:", block + "logit_clip:", 1)
    return header + body


def main(argv: list[str] | None = None) -> int:
    """Fit and (unless --dry-run) write the model, its metadata and params.yaml."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--date", default=datetime.now(UTC).strftime("%Y-%m-%d"), help="fit date written to params.yaml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    import joblib
    import sklearn

    train = load_items(("train",))
    val = load_items(("val",))
    model = train_model(train, args.seed)
    xv = feature_matrix([i.url for i in val])
    yv = np.array([i.label for i in val])
    raw = model.predict_proba(xv)[:, 1]  # type: ignore[attr-defined]
    platt = fit_platt(raw, yv)
    p_clf = apply_platt(platt, raw)

    draft = load_params(PARAMS_YAML)
    scored = [score_url(i.url, float(pc), draft, model_cap=False) for i, pc in zip(val, p_clf, strict=True)]
    p = np.array([s.result.calibrated_probability for s in scored])
    official = np.array([i.official for i in val])
    conflict = np.array([s.brand_conflict for s in scored])
    fired = np.array([bool(s.result.fired_rules) for s in scored])
    th = fit_bands(p, yv, official, p_clf, conflict, draft.h1_p_floor)
    share = t3_share(p, p_clf, conflict, th, fired)
    if share > T3_BUDGET:
        th.notes.append(f"T3 share {share:.3f} exceeds the {T3_BUDGET:.0%} budget on validation (reported, not forced)")

    dataset_hash = manifest_dataset_hash(read_jsonl(ITEMS_MANIFEST))  # recomputed from the verified manifest
    fit_hash = items_hash([*train, *val])  # hash of the items actually loaded for fitting
    sha = git_sha(dirty=False)
    meta: dict[str, object] = {
        "dataset_hash": dataset_hash,
        "fit_items_hash": fit_hash,
        "git_sha": sha,
        "fit_date": args.date,
        "seed": args.seed,
        "n_train": len(train),
        "n_val": len(val),
        "fpr_target": FPR_TARGET,
        "dangerous_fpr_target": DANGEROUS_FPR_TARGET,
        "t3_share_val": round(share, 4),
        "notes": th.notes,
    }
    import dataclasses as _dc

    cap = fit_model_cap(
        val,
        p_clf,
        _dc.replace(draft, tau_low=th.tau_low, tau_high=th.tau_high, eps_low=th.eps_low, eps_high=th.eps_high),
    )
    meta["model_cap_notes"] = cap.notes
    new_yaml = render_params(PARAMS_YAML.read_text(encoding="utf-8"), th, meta, cap)
    import yaml

    params_from_mapping(yaml.safe_load(new_yaml))  # validates the result before anything is written
    print(
        f"tau_low={th.tau_low} tau_high={th.tau_high} eps_low={th.eps_low} eps_high={th.eps_high} "
        f"t3_share_val={share:.3f} notes={th.notes}"
    )
    print(
        f"model_cap margin={cap.margin} strong_adj={cap.strong_adj} val dangerous recall (credential-form pages)="
        f"{cap.recall_form:.4f} legit dangerous rate={cap.fpr_form:.4f}; url-only recall={cap.recall_url_only:.4f}"
    )
    if args.dry_run:
        return 0
    import dataclasses

    (RESULTS_DIR / "published" / "fits").mkdir(parents=True, exist_ok=True)
    artifact = {
        "split": "val",
        "fitted_on": "validation only",
        "dataset_hash": dataset_hash,
        "git_sha": sha,
        "seed": args.seed,
        "grid": {"margin": list(CAP_MARGINS), "strong_adj": list(CAP_STRONG)},
        "constraints": {
            "url_only_dangerous_fpr_max": DANGEROUS_FPR_TARGET,
            "credential_form_dangerous_fpr_max": FPR_TARGET,
        },
        "chosen": dataclasses.asdict(cap),
    }
    (RESULTS_DIR / "published" / "fits" / "model_cap_fit.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"hgb": model, "platt": platt}, MODEL_DIR / MODEL_FILE)
    blob = (MODEL_DIR / MODEL_FILE).read_bytes()
    model_meta = {
        "model_id": "t1_hgb",
        "model_sha256": hashlib.sha256(blob).hexdigest(),
        "algorithm": "sklearn.ensemble.HistGradientBoostingClassifier + Platt calibration (validation)",
        "sklearn_version": sklearn.__version__,
        "joblib_version": joblib.__version__,
        "numpy_version": np.__version__,
        "hyperparameters": HGB_PARAMS,
        "feature_names": list(FEATURE_NAMES),
        "seed": args.seed,
        "dataset_hash": dataset_hash,
        "fit_items_hash": fit_hash,
        "git_sha": sha,
        "fit_date": args.date,
        "n_train": len(train),
        "n_val": len(val),
        "trained_on": "train split only; calibrated and thresholds fitted on validation only",
    }
    (MODEL_DIR / META_FILE).write_text(json.dumps(model_meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    PARAMS_YAML.write_text(new_yaml, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
