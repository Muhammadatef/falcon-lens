"""Metric functions: threshold metrics, PR-AUC, bootstrap CIs, reliability curve and ECE.

Positive class = phishing. A "warning" is a verdict of ``suspicious`` or ``dangerous``.
All functions are pure and deterministic; the bootstrap takes an explicit seed.

When to use it:
    As a library, imported by run.py and the tests; it has no command of its own. No files, no network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

Array = Any


def confusion(y: Sequence[int], pred: Sequence[bool]) -> tuple[int, int, int, int]:
    """Counts (tp, fp, tn, fn) with phishing as the positive class."""
    yt = np.asarray(y, dtype=bool)
    yp = np.asarray(pred, dtype=bool)
    return int((yt & yp).sum()), int((~yt & yp).sum()), int((yt & ~yp).sum()), int((~yt & ~yp).sum())


def _div(a: float, b: float) -> float:
    return a / b if b else float("nan")


def precision(y: Sequence[int], pred: Sequence[bool]) -> float:
    """tp / (tp + fp); 0.0 when undefined."""
    tp, fp, _, _ = confusion(y, pred)
    return _div(tp, tp + fp)


def recall(y: Sequence[int], pred: Sequence[bool]) -> float:
    """tp / (tp + fn); 0.0 when undefined."""
    tp, _, fn, _ = confusion(y, pred)
    return _div(tp, tp + fn)


def fpr(y: Sequence[int], pred: Sequence[bool]) -> float:
    """fp / (fp + tn): share of legitimate items that received a warning."""
    _, fp, _, tn = confusion(y, pred)
    return _div(fp, fp + tn)


def f1(y: Sequence[int], pred: Sequence[bool]) -> float:
    """Harmonic mean of precision and recall."""
    p, r = precision(y, pred), recall(y, pred)
    return _div(2 * p * r, p + r) if not (np.isnan(p) or np.isnan(r)) else float("nan")


def pr_auc(y: Sequence[int], score: Sequence[float]) -> float:
    """Average precision (step-wise area under the PR curve), as sklearn defines it."""
    from sklearn.metrics import average_precision_score

    yt = np.asarray(y)
    if yt.sum() == 0:
        return float("nan")
    return float(average_precision_score(yt, np.asarray(score)))


def reliability(y: Sequence[int], p: Sequence[float], bins: int = 10) -> list[dict[str, float]]:
    """Equal-width bins on [0, 1]: mean predicted p, observed rate and count per non-empty bin."""
    yt = np.asarray(y, dtype=float)
    pp = np.asarray(p, dtype=float)
    idx = np.minimum((pp * bins).astype(int), bins - 1)
    out: list[dict[str, float]] = []
    for b in range(bins):
        m = idx == b
        if m.any():
            out.append(
                {
                    "bin_low": b / bins,
                    "bin_high": (b + 1) / bins,
                    "mean_p": float(pp[m].mean()),
                    "observed": float(yt[m].mean()),
                    "n": int(m.sum()),
                }
            )
    return out


def ece(y: Sequence[int], p: Sequence[float], bins: int = 10) -> float:
    """Expected calibration error: sum over bins of (n_b / n) * |observed_b - mean_p_b|."""
    n = len(y)
    if n == 0:
        return float("nan")
    return float(sum(b["n"] / n * abs(b["observed"] - b["mean_p"]) for b in reliability(y, p, bins)))


def bootstrap_ci(
    stat: Callable[[Array, Array], float],
    y: Sequence[int],
    x: Sequence[Any],
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile bootstrap CI of ``stat(y, x)`` resampling items with replacement.

    Resamples where the statistic is undefined (NaN, e.g. no positives drawn) are dropped; if fewer than half
    survive the interval is (nan, nan).
    """
    yt = np.asarray(y)
    xa = np.asarray(x)
    n = len(yt)
    if n == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    vals: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        v = stat(yt[idx], xa[idx])
        if not np.isnan(v):
            vals.append(v)
    if len(vals) < n_boot / 2:
        return float("nan"), float("nan")
    lo, hi = np.quantile(vals, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def with_ci(
    stat: Callable[[Array, Array], float], y: Sequence[int], x: Sequence[Any], n_boot: int, seed: int
) -> dict[str, float | None]:
    """A metric value together with its bootstrap confidence interval."""
    v = stat(np.asarray(y), np.asarray(x))
    lo, hi = bootstrap_ci(stat, y, x, n_boot, seed)
    return {"value": _clean(v), "ci_low": _clean(lo), "ci_high": _clean(hi)}


def _clean(v: float) -> float | None:
    return None if np.isnan(v) else round(float(v), 6)
