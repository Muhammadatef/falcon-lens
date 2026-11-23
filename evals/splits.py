"""Split assignment, freezing and checking (docs/EVALS.md "Splits").

* grouped by registrable domain: a domain is in exactly one split;
* temporal cut when feasible: every test phishing ``first_seen`` is later than every train one (and val sits between).
  A temporal cut needs at least ``MIN_POLLS`` distinct phishing ``first_seen`` values; with fewer (one OpenPhish poll
  gives a single timestamp) the split falls back to a seeded, domain-grouped random split and the artifact says
  ``temporal_cut: false``. Legit items carry their collection date, not a real first sighting, so the temporal rule
  is applied to phishing items only;
* the test split is frozen: ``evals/splits.lock`` holds the sha256 of the test item ids. Rebuilding keeps every
  already-assigned item in its split. After the freeze a new item goes only to train or val (with its domain's split
  if the domain is already placed); a new item whose domain is already in test is excluded, never added to test.

CLI: ``python -m evals.splits --check`` (reads only the public manifest; needs no private data).

When to use it:
    As a library for the dataset build; the CLI check is also safe to run anywhere, including CI.

How to run:
    uv run python -m evals.splits --check

Outputs / side effects:
    --check prints "splits ok: ..." (exit 0) or FAIL lines (exit 1). Read-only: it never changes the
    manifest or evals/splits.lock (the build step owns those).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from evals.common import ITEMS_MANIFEST, SPLITS_LOCK, read_jsonl, sha256_hex

SPLITS = ("train", "val", "test")
RATIOS = {"train": 0.6, "val": 0.2, "test": 0.2}
MIN_POLLS = 3
EXCLUDED = "excluded"


@dataclass(frozen=True, slots=True)
class SplitItem:
    """The fields the split assignment needs for one item."""

    item_id: str
    label: int  # 1 = phishing
    domain_key: str
    first_seen: str  # ISO timestamp, lexicographically sortable


def temporal_feasible(items: Sequence[SplitItem]) -> bool:
    """True if there are enough distinct polls for a temporal cut."""
    return len({i.first_seen for i in items if i.label == 1}) >= MIN_POLLS


def _fill_random(
    groups: list[tuple[str, list[SplitItem]]],
    rng: random.Random,
    counts: dict[str, int],
    allowed: Sequence[str] = SPLITS,
) -> dict[str, str]:
    """Greedy: each group (shuffled) goes to the allowed split with the largest deficit against RATIOS."""
    groups = sorted(groups, key=lambda g: g[0])
    rng.shuffle(groups)
    out: dict[str, str] = {}
    for _key, members in groups:
        total = sum(counts.values()) + len(members)
        split = max(allowed, key=lambda s: (RATIOS[s] * total - counts[s], s == "train"))
        counts[split] += len(members)
        for m in members:
            out[m.item_id] = split
    return out


def _by_domain(items: Sequence[SplitItem]) -> dict[str, list[SplitItem]]:
    g: dict[str, list[SplitItem]] = defaultdict(list)
    for it in items:
        g[it.domain_key].append(it)
    return g


def _fill_temporal(groups: list[tuple[str, list[SplitItem]]]) -> dict[str, str]:
    """Oldest groups train, newest test; a group straddling a boundary is excluded from the older side."""
    groups = sorted(groups, key=lambda g: (min(i.first_seen for i in g[1]), g[0]))
    total = sum(len(m) for _, m in groups)
    out: dict[str, str] = {}
    seen = 0
    cuts = {"train": RATIOS["train"] * total, "val": (RATIOS["train"] + RATIOS["val"]) * total}
    bucket: dict[str, list[list[SplitItem]]] = {s: [] for s in SPLITS}
    for _key, members in groups:
        s = "train" if seen < cuts["train"] else "val" if seen < cuts["val"] else "test"
        bucket[s].append(members)
        seen += len(members)
    for older, newer in (("val", "test"), ("train", "val"), ("train", "test")):
        if not bucket[newer]:
            continue
        newer_min = min(i.first_seen for m in bucket[newer] for i in m)
        keep = []
        for m in bucket[older]:
            if max(i.first_seen for i in m) >= newer_min:
                for i in m:
                    out[i.item_id] = EXCLUDED
            else:
                keep.append(m)
        bucket[older] = keep
    for s in SPLITS:
        for m in bucket[s]:
            for i in m:
                out[i.item_id] = s
    return out


def assign_splits(
    items: Sequence[SplitItem], seed: int, existing: Mapping[str, str] | None = None
) -> tuple[dict[str, str], bool]:
    """Return ({item_id: split|excluded}, temporal_cut). ``existing`` assignments are frozen and kept."""
    existing = existing or {}
    assigned: dict[str, str] = {}
    domain_split: dict[str, str] = {}
    fresh: list[SplitItem] = []
    for it in items:
        if it.item_id in existing:
            assigned[it.item_id] = existing[it.item_id]
            if existing[it.item_id] in SPLITS:
                domain_split.setdefault(it.domain_key, existing[it.item_id])
    for it in items:
        if it.item_id in assigned:
            continue
        ds = domain_split.get(it.domain_key)
        if ds == "test":
            assigned[it.item_id] = EXCLUDED  # test is frozen: never grows
        elif ds is not None:
            assigned[it.item_id] = ds
        else:
            fresh.append(it)

    rng = random.Random(seed)  # noqa: S311 - reproducible split, not security
    temporal = temporal_feasible(items) and not existing
    counts = {s: sum(1 for v in assigned.values() if v == s) for s in SPLITS}
    # a domain that has any phishing item is grouped into the phishing stratum
    phish_domains = {i.domain_key for i in fresh if i.label == 1}
    pg = list(_by_domain([i for i in fresh if i.domain_key in phish_domains]).items())
    lg = list(_by_domain([i for i in fresh if i.domain_key not in phish_domains]).items())
    # once a freeze exists, test never grows: post-freeze items go to train or val only
    allowed = ("train", "val") if existing else SPLITS
    if temporal:
        assigned.update(_fill_temporal(pg))
    else:
        assigned.update(_fill_random(pg, rng, dict(counts), allowed))
    assigned.update(_fill_random(lg, rng, dict(counts), allowed))
    return assigned, temporal


# ---------------------------------------------------------------- lock + dataset hash


def test_hash(rows: Sequence[Mapping[str, object]]) -> str:
    """SHA-256 over the test item ids (what splits.lock freezes)."""
    ids = sorted(str(r["item_id"]) for r in rows if r["split"] == "test")
    return sha256_hex("\n".join(ids))


test_hash.__test__ = False  # type: ignore[attr-defined]  # not a pytest test


def dataset_hash(rows: Sequence[Mapping[str, object]]) -> str:
    """SHA-256 over all item ids and splits."""
    lines = sorted(f"{r['item_id']}:{r['label']}:{r['split']}" for r in rows if r["split"] != EXCLUDED)
    return sha256_hex("\n".join(lines))


def make_lock(
    rows: Sequence[Mapping[str, object]], seed: int, temporal_cut: bool, post_freeze: Mapping[str, int] | None = None
) -> dict[str, object]:
    """Build the splits.lock content for the given manifest rows."""
    counts = {s: sum(1 for r in rows if r["split"] == s) for s in (*SPLITS, EXCLUDED)}
    return {
        "seed": seed,
        "temporal_cut": temporal_cut,
        "counts": counts,
        "test_sha256": test_hash(rows),
        "dataset_hash": dataset_hash(rows),
        "post_freeze": dict(post_freeze or {}),
    }


def check_rows(rows: Sequence[Mapping[str, object]], lock: Mapping[str, object] | None) -> list[str]:
    """Invariants over the public manifest. Returns human-readable errors (empty = ok)."""
    errors: list[str] = []
    dom_splits: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["split"] in SPLITS:
            dom_splits[str(r["domain_hmac"])].add(str(r["split"]))
        for k in r:
            if k in ("url", "domain", "registrable_domain"):
                errors.append(f"manifest row carries a plain '{k}' field")
    leaked = sum(1 for s in dom_splits.values() if len(s) > 1)
    if leaked:
        errors.append(f"{leaked} registrable domain(s) appear in more than one split")
    if lock is None:
        errors.append("evals/splits.lock is missing")
        return errors
    if lock.get("temporal_cut"):
        phish = [r for r in rows if r["label"] == 1 and r["split"] in SPLITS]
        tr = [str(r["first_seen"]) for r in phish if r["split"] == "train"]
        te = [str(r["first_seen"]) for r in phish if r["split"] == "test"]
        if tr and te and not max(tr) < min(te):
            errors.append("temporal cut violated: max(train.first_seen) >= min(test.first_seen)")
    if test_hash(rows) != lock.get("test_sha256"):
        errors.append("test split hash does not match evals/splits.lock (the test split changed)")
    if dataset_hash(rows) != lock.get("dataset_hash"):
        errors.append("dataset hash does not match evals/splits.lock")
    return errors


def load_lock(path: Path = SPLITS_LOCK) -> dict[str, object] | None:
    """Read evals/splits.lock, or None if it does not exist."""
    return json.loads(path.read_text()) if path.exists() else None


def main(argv: list[str] | None = None) -> int:
    """CLI: `--check` verifies the manifest against the lock."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify split invariants and the lock")
    args = ap.parse_args(argv)
    if not args.check:
        ap.print_help()
        return 2
    rows = read_jsonl(ITEMS_MANIFEST)
    lock = load_lock()
    errors = check_rows(rows, lock)
    for e in errors:
        print(f"FAIL: {e}", file=sys.stderr)
    if not errors and lock is not None:
        print(f"splits ok: {lock['counts']} cut={lock['temporal_cut']} test_sha256={str(lock['test_sha256'])[:12]}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
