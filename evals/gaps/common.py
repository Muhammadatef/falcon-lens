"""Shared pieces for the gap evals: artifact writer, Wilson interval, statistics helpers.

Every artifact states scope, n, 95% CI, data provenance, model route and model id, and the git SHA. Nothing here
holds a metric value: numbers are computed by the area modules and written as they come.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.common import ROOT, git_sha

PUBLISHED = ROOT / "evals" / "results" / "published"
SYSTEM_UNDER_TEST = "fc577d7a5d2f59366f35da287a9be106fe6bb03c"  # origin/main when the model runs were taken
URL_RE = re.compile(r"https?://", re.IGNORECASE)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion k/n (95% by default). (0, 0) when n is 0."""
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(k: int, n: int) -> dict[str, Any]:
    """A proportion with its Wilson 95% CI and the counts it came from."""
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "value": (k / n) if n else None, "ci95": [round(lo, 4), round(hi, 4)]}


def pctl(vals: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in 0..100); None for no data."""
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return float(s[0])
    pos = (len(s) - 1) * q / 100.0
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(s) - 1)
    return float(s[lo] + (s[hi] - s[lo]) * (pos - lo))


def mean_ci(vals: Sequence[float], n_boot: int = 2000, seed: int = 20261122) -> dict[str, Any]:
    """Mean with a percentile-bootstrap 95% CI."""
    import numpy as np

    if not vals:
        return {"n": 0, "mean": None, "ci95": None}
    a = np.asarray(vals, dtype=float)
    rng = np.random.default_rng(seed)
    means = [float(rng.choice(a, size=len(a), replace=True).mean()) for _ in range(n_boot)]
    return {
        "n": int(len(a)),
        "mean": round(float(a.mean()), 6),
        "ci95": [round(float(np.percentile(means, 2.5)), 6), round(float(np.percentile(means, 97.5)), 6)],
    }


def not_evaluated(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "not_evaluated", "reason": reason, **extra}


def envelope(
    area: str,
    *,
    scope: str,
    provenance: str,
    n: int | dict[str, int],
    route: str,
    model_ids: dict[str, Any],
    body: dict[str, Any],
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """The common artifact header plus the area body."""
    return {
        "schema_version": 1,
        "area": area,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": git_sha(),
        "system_under_test": {
            "commit": SYSTEM_UNDER_TEST,
            "note": "the cascade and Sentinel runs behind this artifact were taken on this commit (origin/main when "
            "the jobs started); main moved on afterwards and the model runs were not repeated. The offline parts "
            "(no model) were recomputed at git_sha and checked equal on the synthetic split.",
        },
        "scope": scope,
        "provenance": provenance,  # synthetic | fixture | real | mixed (see body)
        "n": n,
        "ci_method": "Wilson 95% for proportions; percentile bootstrap (2000, seed 20261122) for means",
        "model_route": route,
        "model_ids": model_ids,
        "notes": notes or [],
        **body,
    }


def write_artifact(area: str, doc: dict[str, Any], stem: str | None = None) -> Path:
    """Write ``published/<area>/<stem>_<sha8>_<ts>.json``. Refuses a document that contains a URL."""
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if URL_RE.search(text):
        raise ValueError(f"artifact for {area} contains a URL; defang it first")
    out = PUBLISHED / area
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    sha = str(doc.get("git_sha", "nosha"))[:8]
    path = out / f"{stem or area}_{sha}_{ts}.json"
    path.write_text(text, encoding="utf-8")
    return path
