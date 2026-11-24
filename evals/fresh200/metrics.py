"""Pure aggregation for the fresh-200 live run: confusion metrics with Wilson and bootstrap 95% intervals.

Every number in the published artifact comes from these functions applied to the raw per-URL results.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

WARN = ("suspicious", "dangerous")
# Failures only the browser-to-target leg can produce (docs/SCORING.md "Page not opened"): the page was not reachable.
RENDER_FAIL = frozenset({"timeout", "dns_failure", "tls_error", "http_403_empty", "empty_response"})


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


def _q(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    i = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return float(sorted_vals[i])


def percentile(vals: Sequence[float], q: float) -> float:
    return _q(sorted(vals), q)


def bootstrap(
    items: Sequence[Any], stat: Callable[[Sequence[Any]], float], n_boot: int = 2000, seed: int = 7
) -> list[float]:
    """Percentile bootstrap 95% CI of ``stat`` over ``items`` (resampling items with replacement)."""
    if not items:
        return [0.0, 0.0]
    rng = random.Random(seed)  # noqa: S311 - statistics, not security
    n = len(items)
    vals = sorted(stat([items[rng.randrange(n)] for _ in range(n)]) for _ in range(n_boot))
    return [vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot) - 1]]


def is_live(r: dict[str, Any]) -> bool:
    """Was the page opened in the sandbox? False when the sandbox reported a render failure for the target."""
    if "sandbox.not_rendered" in r.get("signals", []):
        return False
    return not (set(r.get("degraded_reasons", [])) & RENDER_FAIL)


def _flag(r: dict[str, Any], dangerous_only: bool) -> bool:
    return r["verdict"] == "dangerous" if dangerous_only else r["verdict"] in WARN


def _ratio(
    k: int, n: int, with_boot: list[Any] | None = None, fn: Callable[[Sequence[Any]], float] | None = None
) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    out: dict[str, Any] = {
        "k": k,
        "n": n,
        "value": round(k / n, 4) if n else None,
        "wilson95": [round(lo, 4), round(hi, 4)],
    }
    if with_boot is not None and fn is not None:
        out["bootstrap95"] = [round(x, 4) for x in bootstrap(with_boot, fn)]
    return out


def _prf(rows: Sequence[dict[str, Any]], dangerous_only: bool) -> tuple[float, float, float, float]:
    tp = sum(1 for r in rows if r["label"] == 1 and _flag(r, dangerous_only))
    fn = sum(1 for r in rows if r["label"] == 1 and not _flag(r, dangerous_only))
    fp = sum(1 for r in rows if r["label"] == 0 and _flag(r, dangerous_only))
    tn = sum(1 for r in rows if r["label"] == 0 and not _flag(r, dangerous_only))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    acc = (tp + tn) / len(rows) if rows else 0.0
    return prec, rec, f1, acc


def overall(rows: list[dict[str, Any]], dangerous_only: bool) -> dict[str, Any]:
    """Confusion metrics over labelled rows. ``dangerous_only`` counts only 'dangerous' as a warning."""
    pos = [r for r in rows if r["label"] == 1]
    neg = [r for r in rows if r["label"] == 0]
    tp = sum(_flag(r, dangerous_only) for r in pos)
    fp = sum(_flag(r, dangerous_only) for r in neg)
    return {
        "counts": {"tp": tp, "fn": len(pos) - tp, "fp": fp, "tn": len(neg) - fp},
        "recall": _ratio(tp, len(pos), pos, lambda s: sum(_flag(r, dangerous_only) for r in s) / len(s)),
        "false_positive_rate": _ratio(fp, len(neg), neg, lambda s: sum(_flag(r, dangerous_only) for r in s) / len(s)),
        "precision": {
            **_ratio(tp, tp + fp),
            "bootstrap95": [round(x, 4) for x in bootstrap(rows, lambda s: _prf(s, dangerous_only)[0])],
        },
        "f1": {
            "value": round(_prf(rows, dangerous_only)[2], 4),
            "bootstrap95": [round(x, 4) for x in bootstrap(rows, lambda s: _prf(s, dangerous_only)[2])],
        },
        "accuracy": {
            **_ratio(tp + len(neg) - fp, len(rows)),
            "bootstrap95": [round(x, 4) for x in bootstrap(rows, lambda s: _prf(s, dangerous_only)[3])],
        },
    }


def group_stats(rows: list[dict[str, Any]], dangerous_only_too: bool = True) -> dict[str, Any]:
    """Per-group descriptive stats: verdict mix, degraded rate, latency, tier mix, AI-step use."""
    n = len(rows)
    lat = [r["latency_s"] for r in rows if r.get("latency_s") is not None]
    deg = sum(1 for r in rows if r["degraded"])
    out: dict[str, Any] = {
        "n": n,
        "verdicts": dict(Counter(r["verdict"] for r in rows)),
        "warned": _ratio(sum(r["verdict"] in WARN for r in rows), n),
        "dangerous": _ratio(sum(r["verdict"] == "dangerous" for r in rows), n),
        "degraded": _ratio(deg, n),
        "degraded_reasons": dict(Counter(x for r in rows for x in r.get("degraded_reasons", []))),
        "latency_s": {
            "p50": round(percentile(lat, 0.5), 2),
            "p95": round(percentile(lat, 0.95), 2),
            "max": round(max(lat, default=0.0), 2),
        },
        "tier_mix": dict(sorted(Counter(r["tier"] for r in rows).items(), key=lambda kv: str(kv[0]))),
        "reached_t3_investigator": _ratio(sum(r["tier"] == "T3" for r in rows), n),
        "llm_evidence_present": _ratio(sum(any(s.startswith("llm.") for s in r.get("signals", [])) for r in rows), n),
    }
    return out


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: completed checks with label, group, verdict, degraded, tier, latency_s, signals, degraded_reasons."""
    phish = [r for r in rows if r["label"] == 1]
    legit = [r for r in rows if r["label"] == 0]
    live = [r for r in phish if is_live(r)]
    dead = [r for r in phish if not is_live(r)]
    on_live = live + legit  # fair test: dead phishing pages removed
    return {
        "n_completed": len(rows),
        "overall_all_phishing": {"any_warning": overall(rows, False), "dangerous_only": overall(rows, True)},
        "overall_live_phishing_only": {
            "any_warning": overall(on_live, False),
            "dangerous_only": overall(on_live, True),
        },
        "groups": {
            "phishing_all": group_stats(phish),
            "phishing_live_in_sandbox": group_stats(live),
            "phishing_dead_in_sandbox": group_stats(dead),
            "phishing_reputation_feed_hit": group_stats([r for r in phish if r.get("rep_hit")]),
            "phishing_no_reputation_hit": group_stats([r for r in phish if not r.get("rep_hit")]),
            "phishing_live_no_reputation_hit": group_stats([r for r in live if not r.get("rep_hit")]),
            "legit_all": group_stats(legit),
            "legit_global": group_stats([r for r in legit if r["group"] == "legit_global"]),
            "legit_uae": group_stats([r for r in legit if r["group"] == "legit_uae"]),
        },
        "latency_s_all": {
            "p50": round(percentile([r["latency_s"] for r in rows], 0.5), 2),
            "p95": round(percentile([r["latency_s"] for r in rows], 0.95), 2),
        },
        "degraded_rate_all": _ratio(sum(r["degraded"] for r in rows), len(rows)),
    }


def defang(url: str, host_only: bool = False) -> str:
    """hxxp / [.] form. ``host_only`` drops path and query (used for phishing rows: the feed bars redistribution)."""
    from urllib.parse import urlsplit

    p = urlsplit(url)
    scheme = "hxxps" if p.scheme == "https" else "hxxp"
    host = (p.hostname or "").replace(".", "[.]")
    rest = "/…" if host_only else (p.path or "/") + (("?" + p.query) if p.query else "")
    return f"{scheme}://{host}{rest}"
