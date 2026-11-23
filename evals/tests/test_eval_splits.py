import pytest

from evals.splits import (
    EXCLUDED,
    SplitItem,
    assign_splits,
    check_rows,
    dataset_hash,
    make_lock,
    temporal_feasible,
)


def _items(n_phish=60, n_legit=60, polls=1):
    out = []
    for i in range(n_phish):
        out.append(SplitItem(f"p{i}", 1, f"dp{i % 40}", f"2026-11-{10 + i % polls:02d}T00:00:00Z"))
    for i in range(n_legit):
        out.append(SplitItem(f"l{i}", 0, f"dl{i % 50}", "2026-11-22T00:00:00Z"))
    return out


def _rows(items, assigned):
    return [
        {
            "item_id": i.item_id,
            "label": i.label,
            "domain_hmac": i.domain_key,
            "first_seen": i.first_seen,
            "split": assigned[i.item_id],
        }
        for i in items
    ]


def test_no_domain_in_two_splits_and_deterministic():
    items = _items()
    a, temporal = assign_splits(items, seed=1)
    b, _ = assign_splits(items, seed=1)
    assert a == b and not temporal
    by_dom = {}
    for i in items:
        by_dom.setdefault(i.domain_key, set()).add(a[i.item_id])
    assert all(len(s) == 1 for s in by_dom.values())
    assert {"train", "val", "test"} <= set(a.values())


def test_one_poll_is_not_temporal():
    assert not temporal_feasible(_items(polls=1))
    assert temporal_feasible(_items(polls=4))


def test_temporal_cut_when_feasible():
    items = _items(polls=6)
    a, temporal = assign_splits(items, seed=1)
    assert temporal
    rows = _rows(items, a)
    lock = make_lock(rows, 1, True)
    assert check_rows(rows, lock) == []
    tr = max(r["first_seen"] for r in rows if r["split"] == "train" and r["label"] == 1)
    te = min(r["first_seen"] for r in rows if r["split"] == "test" and r["label"] == 1)
    assert tr < te


def test_test_split_frozen_and_hash_detects_change():
    items = _items()
    a, _ = assign_splits(items, 1)
    rows = _rows(items, a)
    lock = make_lock(rows, 1, False)
    assert check_rows(rows, lock) == []
    moved = [dict(r) for r in rows]
    victim = next(r for r in moved if r["split"] == "test")
    victim["split"] = "train"
    assert any("test split" in e for e in check_rows(moved, lock))


def test_new_items_never_enter_frozen_test():
    items = _items()
    a, _ = assign_splits(items, 1)
    test_dom = next(i.domain_key for i in items if a[i.item_id] == "test")
    new = [*items, SplitItem("new1", 1, test_dom, "2026-12-01T00:00:00Z"), SplitItem("new2", 0, "fresh", "x")]
    b, _ = assign_splits(new, 1, existing=a)
    assert b["new1"] == EXCLUDED
    assert b["new2"] in ("train", "val")
    assert all(b[k] == v for k, v in a.items())


def test_domain_leak_detected():
    rows = [
        {"item_id": "a", "label": 1, "domain_hmac": "d", "first_seen": "t", "split": "train"},
        {"item_id": "b", "label": 1, "domain_hmac": "d", "first_seen": "t", "split": "test"},
    ]
    assert any("more than one split" in e for e in check_rows(rows, make_lock(rows, 1, False)))


def test_plain_url_field_rejected():
    rows = [{"item_id": "a", "label": 1, "domain_hmac": "d", "first_seen": "t", "split": "train", "url": "x"}]
    assert any("plain" in e for e in check_rows(rows, make_lock(rows, 1, False)))


def test_committed_manifest_and_lock_are_consistent():
    """Runs on CI too: needs only the public manifest and splits.lock."""
    from evals.common import ITEMS_MANIFEST, read_jsonl
    from evals.splits import load_lock

    rows = read_jsonl(ITEMS_MANIFEST)
    assert check_rows(rows, load_lock()) == []
    assert dataset_hash(rows) == load_lock()["dataset_hash"]


def test_post_freeze_items_never_change_test_hash_and_are_deterministic() -> None:
    from evals.splits import test_hash as _test_hash

    items = _items()  # type: ignore[no-untyped-call]
    first, _ = assign_splits(items, seed=1)
    before = _test_hash(_rows(items, first))  # type: ignore[no-untyped-call]
    new = [SplitItem(f"n{i}", 1, f"dn{i % 70}", "2026-11-23T00:00:00Z") for i in range(300)]
    test_dom = next(i.domain_key for i in items if first[i.item_id] == "test")
    new.append(SplitItem("on_test_domain", 1, test_dom, "2026-11-23T00:00:00Z"))
    allitems = items + new
    a, _ = assign_splits(allitems, seed=1, existing=first)
    b, _ = assign_splits(allitems, seed=1, existing=first)
    assert a == b
    assert _test_hash(_rows(allitems, a)) == before  # type: ignore[no-untyped-call]
    assert a["on_test_domain"] == EXCLUDED
    fresh = [a[i.item_id] for i in new if i.item_id != "on_test_domain"]
    assert set(fresh) == {"train", "val"}


def test_fit_refuses_test_split():
    from evals.train.fit import TestSplitAccess, load_items

    with pytest.raises(TestSplitAccess):
        load_items(("train", "test"))
