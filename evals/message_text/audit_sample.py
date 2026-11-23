"""Supervisor audit sample for the message-text dataset.

Draws a seeded, stratified (split x label x language) random sample of at least 20% of the items and at least 30,
and writes a review sheet (JSONL) with empty ``audit_label`` / ``audit_ok`` / ``notes`` fields. The supervisor checks
that (1) the label is right, (2) the Arabic reads native, (3) there is no link, real brand or real phone, and
(4) a legitimate item really asks for nothing. An error rate above 5% rejects the batch (CLAUDE.md).

Usage: ``uv run python -m evals.message_text.audit_sample [--out work/audit/message_text_sample.jsonl] [--seed N]``
Read-only on the dataset; the sheet goes under work/ (gitignored). It lists test items too: auditing them reveals
nothing to the model, it only checks the labels.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

from evals.message_text.data import load_all

SEED = 20261124
MIN_N = 30
FRACTION = 0.20


def sample(rows: list[dict], seed: int = SEED) -> list[dict]:
    n_target = max(MIN_N, math.ceil(FRACTION * len(rows)))
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["split"], r["label"], r["language"])].append(r)
    rng = random.Random(seed)  # noqa: S311 - audit sampling, not security
    chosen: list[dict] = []
    for key in sorted(groups):
        g = sorted(groups[key], key=lambda r: r["id"])
        k = max(1, math.ceil(len(g) * n_target / len(rows)))
        chosen += rng.sample(g, min(k, len(g)))
    rest = sorted((r for r in rows if r not in chosen), key=lambda r: r["id"])
    rng.shuffle(rest)
    while len(chosen) < n_target and rest:
        chosen.append(rest.pop())
    return sorted(chosen, key=lambda r: r["id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work/audit/message_text_sample.jsonl")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args(argv)
    rows = load_all()
    s = sample(rows, a.seed)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in s:
            f.write(
                json.dumps(
                    {k: r[k] for k in ("id", "split", "label", "language", "subtype", "text")}
                    | {"audit_label": None, "audit_ok": None, "notes": ""},
                    ensure_ascii=False,
                )
                + "\n"
            )
    print(f"{len(s)} of {len(rows)} items ({len(s) / len(rows):.0%}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
