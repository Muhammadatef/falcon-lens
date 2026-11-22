from dataclasses import replace

import pytest

from evals.datasets.build import Item
from evals.splits import make_lock
from evals.train.fit import SplitIntegrityError, load_items


def _fixture():
    items = []
    for n, (label, split) in enumerate([(1, "train"), (0, "train"), (1, "val"), (0, "val"), (1, "test"), (0, "test")]):
        items.append(
            Item(f"i{n}", f"u{n}", label, f"d{n}", "2026-11-22T00:00:00Z", "c", "real", "s", True, False, False, split)
        )
    rows = [
        {
            "item_id": i.item_id,
            "label": i.label,
            "domain_hmac": i.domain_hmac,
            "first_seen": i.first_seen,
            "split": i.split,
        }
        for i in items
    ]
    return items, rows, make_lock(rows, 1, False)


def test_fit_accepts_consistent_cache():
    items, rows, lock = _fixture()
    got = load_items(("train", "val"), items, rows, lock)
    assert {i.split for i in got} == {"train", "val"} and len(got) == 4


def test_fit_refuses_relabelled_cache():
    """A cache that moves a test item into train must be refused, not silently trained on."""
    items, rows, lock = _fixture()
    bad = [replace(i, split="train") if i.split == "test" else i for i in items]
    with pytest.raises(SplitIntegrityError):
        load_items(("train", "val"), bad, rows, lock)


def test_fit_refuses_missing_extra_or_relabelled_items():
    items, rows, lock = _fixture()
    with pytest.raises(SplitIntegrityError):
        load_items(("train",), items[:-1], rows, lock)
    with pytest.raises(SplitIntegrityError):
        load_items(("train",), [*items, replace(items[0], item_id="zz")], rows, lock)
    with pytest.raises(SplitIntegrityError):
        load_items(("train",), [replace(items[0], label=0), *items[1:]], rows, lock)


def test_fit_refuses_manifest_that_fails_lock():
    items, rows, lock = _fixture()
    tampered = [dict(r) for r in rows]
    tampered[4]["split"] = "train"
    with pytest.raises(SplitIntegrityError):
        load_items(("train", "val"), items, tampered, lock)
