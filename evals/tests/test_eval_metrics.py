import numpy as np
import pytest
from sklearn import metrics as skm

from evals.harness import metrics as M

rng = np.random.default_rng(3)
Y = rng.integers(0, 2, 200)
S = np.clip(Y * 0.3 + rng.random(200) * 0.7, 0, 1)
PRED = S > 0.5


def test_threshold_metrics_match_sklearn():
    assert M.precision(Y, PRED) == pytest.approx(skm.precision_score(Y, PRED))
    assert M.recall(Y, PRED) == pytest.approx(skm.recall_score(Y, PRED))
    assert M.f1(Y, PRED) == pytest.approx(skm.f1_score(Y, PRED))
    tn, fp, _, _ = skm.confusion_matrix(Y, PRED).ravel()
    assert M.fpr(Y, PRED) == pytest.approx(fp / (fp + tn))


def test_pr_auc_matches_sklearn():
    assert M.pr_auc(Y, S) == pytest.approx(skm.average_precision_score(Y, S))


def test_ece_known_values():
    assert M.ece([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0]) == 0.0
    assert M.ece([1, 0], [0.5, 0.5]) == pytest.approx(0.0)
    assert M.ece([0, 0, 0, 0], [0.9, 0.9, 0.9, 0.9]) == pytest.approx(0.9)
    assert sum(b["n"] for b in M.reliability(Y, S)) == len(Y)


def test_bootstrap_deterministic_and_brackets():
    def stat(y, x):
        return M.recall(y, x.astype(bool))

    a = M.bootstrap_ci(stat, Y, PRED, 200, seed=7)
    b = M.bootstrap_ci(stat, Y, PRED, 200, seed=7)
    c = M.bootstrap_ci(stat, Y, PRED, 200, seed=8)
    assert a == b and a != c
    assert a[0] <= M.recall(Y, PRED) <= a[1]


def test_undefined_stat_is_none():
    r = M.with_ci(lambda y, x: M.precision(y, x.astype(bool)), [0, 0], [False, False], 50, 1)
    assert r["value"] is None
