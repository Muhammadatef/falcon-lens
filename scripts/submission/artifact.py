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

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "evals" / "results" / "published"
NO_ARTIFACT = "Evaluation in progress"
PROVENANCE_KEYS = ("created_at", "timestamp", "git_sha", "dataset_hash", "split", "route", "source")


@dataclass(frozen=True)
class Artifact:
    path: Path
    data: dict[str, Any]
    leaves: list[tuple[str, Any]] = field(default_factory=list)

    @property
    def metrics(self) -> list[tuple[str, Any]]:
        """Flattened (dotted.key, value) pairs under `metrics`, scalars only, in file order."""
        node = self.data.get("metrics")
        if not isinstance(node, dict):
            return []
        return [(k, v) for k, v in flatten(node) if isinstance(v, int | float | str) and not isinstance(v, bool)]

    @property
    def provenance(self) -> list[tuple[str, Any]]:
        return [(key, self.data[key]) for key in PROVENANCE_KEYS if isinstance(self.data.get(key), str | int | float)]


def flatten(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Depth-first (dotted.path, leaf) pairs. List items get `[i]` suffixes."""
    if isinstance(node, dict):
        rows: list[tuple[str, Any]] = []
        for key, value in node.items():
            rows.extend(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return rows
    if isinstance(node, list):
        rows = []
        for index, item in enumerate(node):
            rows.extend(flatten(item, f"{prefix}[{index}]"))
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
