#!/usr/bin/env python3
"""Inject published eval numbers into README.md, and nothing else.

Truthfulness rule (CLAUDE.md): every metric shown anywhere comes from a generated
eval artifact. This script is the only writer of the block between

    <!-- metrics:start -->  and  <!-- metrics:end -->

in README.md. It copies values verbatim from the newest JSON file under
``evals/results/published/``; it never rounds, computes or estimates. Until an
artifact exists the block reads "No published eval artifact yet".

Usage:
    python scripts/readme_metrics.py           # rewrite the README block
    python scripts/readme_metrics.py --check   # exit 1 if the block is stale
    python scripts/readme_metrics.py --print   # print the block, change nothing

Standard library only, so it runs before `uv sync`.

When to use it:
    After a new eval artifact is published (`make eval` with --publish), and in CI with --check.

How to run:
    python scripts/readme_metrics.py [--check | --print] [--readme PATH] [--published DIR]
    Run from the repo root. Uses only the standard library.

Outputs / side effects:
    Without flags it rewrites only the block between the metrics:start and metrics:end markers in README.md.
    --check changes nothing and exits 1 if the block is stale; --print shows the block and changes nothing.
    No network access. It never computes, rounds or estimates a number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
START = "<!-- metrics:start -->"
END = "<!-- metrics:end -->"
NO_ARTIFACT = "No published eval artifact yet"

# Provenance fields copied when present (docs/EVALS.md, "Artifact").
PROVENANCE_KEYS = (
    "created_at",
    "timestamp",
    "git_sha",
    "dataset_hash",
    "split",
    "source",
    "seeds",
    "seed",
)
MODEL_KEYS = ("models", "model_ids")


def latest_artifact(published: Path) -> Path | None:
    """Newest artifact by file name (artifacts are named `<timestamp>.json`)."""
    files = sorted(p for p in published.glob("*.json") if p.is_file())
    return files[-1] if files else None


def _cell(value: Any) -> str:
    """Exact JSON text of a value, made safe for a Markdown table cell."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\n", " ")


def flatten(node: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Depth-first list of (dotted.path, leaf). Lists of scalars stay one leaf."""
    if isinstance(node, dict):
        rows: list[tuple[str, Any]] = []
        for key, value in node.items():
            rows.extend(flatten(value, f"{prefix}.{key}" if prefix else str(key)))
        return rows
    if isinstance(node, list) and any(isinstance(item, dict | list) for item in node):
        rows = []
        for index, item in enumerate(node):
            rows.extend(flatten(item, f"{prefix}[{index}]"))
        return rows
    return [(prefix, node)]


def render(published: Path, root: Path = ROOT) -> str:
    """Markdown for the README block (without the markers)."""
    artifact = latest_artifact(published)
    if artifact is None:
        return (
            f"_{NO_ARTIFACT}._ Numbers appear here only when `make eval` has written an "
            "artifact and a copy is in `evals/results/published/`."
        )
    data = json.loads(artifact.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{artifact}: expected a JSON object at the top level")

    try:
        shown = artifact.relative_to(root).as_posix()
    except ValueError:
        shown = artifact.name
    lines = [f"Source artifact: [`{shown}`]({shown}). Values are copied verbatim.", ""]

    provenance = [(key, data[key]) for key in PROVENANCE_KEYS if key in data]
    for key in MODEL_KEYS:
        if key in data:
            provenance.extend(flatten(data[key], key))
    if provenance:
        lines += ["| Provenance | Value |", "|---|---|"]
        lines += [f"| `{key}` | `{_cell(value)}` |" for key, value in provenance]
        lines.append("")

    metrics = flatten(data["metrics"]) if "metrics" in data else []
    if metrics:
        lines += ["| Metric | Value |", "|---|---|"]
        lines += [f"| `{key}` | {_cell(value)} |" for key, value in metrics]
    else:
        lines.append("_The artifact has no `metrics` object, so no numbers are shown._")
    return "\n".join(lines).rstrip()


def inject(readme_text: str, block: str) -> str:
    """Replace the text between the markers. Both markers must exist exactly once."""
    if readme_text.count(START) != 1 or readme_text.count(END) != 1:
        raise ValueError(f"README must contain exactly one {START} and one {END}")
    head, rest = readme_text.split(START)
    _, tail = rest.split(END)
    return f"{head}{START}\n{block}\n{END}{tail}"


def main(argv: list[str] | None = None) -> int:
    """Rewrite, check or print the README metrics block (see module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--readme", type=Path, default=ROOT / "README.md")
    parser.add_argument("--published", type=Path, default=ROOT / "evals" / "results" / "published")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 if the README block is stale")
    mode.add_argument("--print", action="store_true", dest="print_only", help="print only")
    args = parser.parse_args(argv)

    block = render(args.published)
    print(block)
    if args.print_only:
        return 0

    current = args.readme.read_text(encoding="utf-8")
    updated = inject(current, block)
    if args.check:
        if updated != current:
            print("README metrics block is stale: run scripts/readme_metrics.py", file=sys.stderr)
            return 1
        return 0
    if updated != current:
        args.readme.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
