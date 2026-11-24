# ruff: noqa: E501
"""Read the newest published eval artifact. The only source of numbers for the submission.

Assumed shape (same assumption as scripts/readme_metrics.py, logged in DECISIONS.md): a JSON
object in `evals/results/published/`, named so that the newest file sorts last
(`<timestamp>.json`), with the numbers under a top-level `metrics` key. Values are copied
verbatim: nothing here rounds, computes or estimates.

Standard library only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from submission import evidence as evidence_mod

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "evals" / "results" / "published"
NO_ARTIFACT = "Evaluation in progress"
PROVENANCE_KEYS = ("created_at", "timestamp", "git_sha", "dataset_hash", "split", "route", "source")
SHORT_HASH = 12  # characters of a git SHA or dataset hash shown on a slide


@dataclass(frozen=True)
class Artifact:
    path: Path
    data: dict[str, Any]
    leaves: list[tuple[str, Any]] = field(default_factory=list)

    @property
    def metrics(self) -> list[tuple[str, Any]]:
        """(key, value) pairs under `metrics` in file order. A list of scalars (a confidence interval) stays one value."""
        node = self.data.get("metrics")
        if not isinstance(node, dict):
            return []
        return [(k, v) for k, v in flatten(node, scalar_lists=True) if not isinstance(v, bool) and v is not None]

    @property
    def provenance(self) -> list[tuple[str, Any]]:
        """Provenance values. A long hexadecimal value is cut to its first SHORT_HASH characters."""
        rows = []
        for key in PROVENANCE_KEYS:
            value = self.data.get(key)
            if (
                isinstance(value, str)
                and len(value) > SHORT_HASH
                and all(c in "0123456789abcdef" for c in value[:SHORT_HASH])
            ):
                value = value[:SHORT_HASH]
            if isinstance(value, str | int | float) and not isinstance(value, bool):
                rows.append((key, value))
        return rows

    @property
    def scope(self) -> str:
        """What the run covered, in the artifact's own words (empty when it does not say)."""
        value = self.data.get("scope")
        return value if isinstance(value, str) else ""

    @property
    def not_evaluated(self) -> list[str]:
        value = self.data.get("not_evaluated")
        keys = [str(item) for item in value] if isinstance(value, list) else []
        return evidence_mod.still_not_measured(keys, self.path.parent)


def flatten(node: Any, prefix: str = "", scalar_lists: bool = False) -> list[tuple[str, Any]]:
    """Depth-first (dotted.path, leaf) pairs. List items get `[i]` suffixes.

    With `scalar_lists`, a list that holds only scalars is returned as one leaf.
    """
    if isinstance(node, dict):
        rows: list[tuple[str, Any]] = []
        for key, value in node.items():
            rows.extend(flatten(value, f"{prefix}.{key}" if prefix else str(key), scalar_lists))
        return rows
    if isinstance(node, list):
        if scalar_lists and not any(isinstance(item, dict | list) for item in node):
            return [(prefix, node)]
        rows = []
        for index, item in enumerate(node):
            rows.extend(flatten(item, f"{prefix}[{index}]", scalar_lists))
        return rows
    return [(prefix, node)]


def latest_path(published: Path = PUBLISHED) -> Path | None:
    files = sorted(p for p in published.glob("*.json") if p.is_file())
    return files[-1] if files else None


def load(published: Path = PUBLISHED) -> Artifact | None:
    """Newest artifact, or None when nothing is published. A malformed file raises."""
    path = latest_path(published)
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object at the top level")
    return Artifact(path=path, data=data, leaves=flatten(data))


def show(value: Any) -> str:
    """Exact JSON text of a value (verbatim; no rounding, no percent conversion)."""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def load_fp_regress(published: Path = PUBLISHED) -> dict[str, Any] | None:
    """Newest live held-out false-alarm run (`published/fp_regress/*.json`, by `created_at`), or None.

    Only runs that carry a `false_positive_rate` with a `value` and a `ci95` count. The numbers in it
    are traceable like the main artifact's metrics (check_numbers.traceable_for).
    """
    best: dict[str, Any] | None = None
    for path in sorted((published / "fp_regress").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rate = data.get("false_positive_rate") if isinstance(data, dict) else None
        if not (isinstance(rate, dict) and "value" in rate and "ci95" in rate and "n" in data and "target" in data):
            continue
        if best is None or str(data.get("created_at", "")) >= str(best.get("created_at", "")):
            best = data
            best["_file"] = path.name
    return best
