"""Assemble the labelled eval set and write the public (HMAC-hashed) manifest, the private item cache and the lock.

Inputs
* phishing: private OpenPhish rows ``data/private/feeds/openphish/2*.jsonl`` (never committed, never printed);
* legit: ``evals/datasets/legit_urls.csv`` (defanged, committed);
* optional ``data/private/datasets/extra_items.jsonl``: later polls, Falcon Demo Bank fixtures or items marked
  zero-day. Row: ``{url, label, first_seen, on_blocklist, kind, category, source}``.

Zero-day = phishing NOT on any enabled blocklist at collection. Every OpenPhish row is by definition listed on
OpenPhish, so the OpenPhish rows contribute nothing to the zero-day subset. Until fixtures or marked items are added
the zero-day subset is empty and zero-day metrics are reported ``not_evaluated`` (EVALS target: >= 40).

Outputs
* ``evals/manifests/items.manifest.jsonl`` public: HMAC ids and domain hashes, no URL, no plain domain;
* ``data/private/datasets/items.jsonl`` private: the same rows plus the URL (read by train/eval);
* ``evals/splits.lock`` created on first build; later builds must reproduce its test hash or fail.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, dataclass

from evals.common import (
    ITEMS_MANIFEST,
    LEGIT_CSV,
    SEED,
    SPLITS_LOCK,
    get_key,
    hmac_hex,
    private_dir,
    read_jsonl,
    refang,
    registrable_domain,
    write_jsonl,
)
from evals.splits import SplitItem, assign_splits, check_rows, load_lock, make_lock


@dataclass(frozen=True, slots=True)
class Item:
    item_id: str
    url: str  # private
    label: int
    domain_hmac: str
    first_seen: str
    category: str
    kind: str  # real | synthetic
    source: str
    on_blocklist: bool
    zero_day: bool
    official: bool
    split: str = ""


PUBLIC_FIELDS = (
    "item_id",
    "label",
    "domain_hmac",
    "first_seen",
    "category",
    "kind",
    "source",
    "on_blocklist",
    "zero_day",
    "official",
    "split",
)


def items_path():  # type: ignore[no-untyped-def]
    return private_dir() / "datasets" / "items.jsonl"


def collect_items(key: bytes) -> list[Item]:
    from falcon_core.signals.brands.registry import default_registry

    reg = default_registry()
    out: dict[str, Item] = {}

    def add(url: str, label: int, first_seen: str, category: str, kind: str, source: str, on_bl: bool) -> None:
        iid = hmac_hex(key, url)
        if iid in out:
            return
        dom = registrable_domain(url)
        out[iid] = Item(
            item_id=iid,
            url=url,
            label=label,
            domain_hmac=hmac_hex(key, dom),
            first_seen=first_seen,
            category=category,
            kind=kind,
            source=source,
            on_blocklist=on_bl,
            zero_day=bool(label == 1 and not on_bl),
            official=bool(label == 0 and reg.is_official(dom)),
        )

    feeds = private_dir() / "feeds" / "openphish"
    for f in sorted(feeds.glob("2*.jsonl")):
        for r in read_jsonl(f):
            add(str(r["url"]), 1, str(r["first_seen"]), "phishing_openphish", "real", "openphish_community", True)
    with LEGIT_CSV.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            kind = "synthetic" if row["source"].lower().startswith("synthetic") else "real"
            add(
                refang(row["url"]),
                0,
                f"{row['first_seen']}T00:00:00Z",
                row["category"],
                kind,
                row["source"][:60],
                False,
            )
    extra = private_dir() / "datasets" / "extra_items.jsonl"
    if extra.exists():
        for r in read_jsonl(extra):
            add(
                str(r["url"]),
                int(str(r["label"])),
                str(r["first_seen"]),
                str(r.get("category", "extra")),
                str(r.get("kind", "real")),
                str(r.get("source", "extra"))[:60],
                bool(r.get("on_blocklist", False)),
            )
    return list(out.values())


def build(seed: int = SEED, refreeze: bool = False) -> tuple[list[Item], dict[str, object]]:
    key = get_key(create=True)
    items = collect_items(key)
    existing: dict[str, str] = {}
    if ITEMS_MANIFEST.exists() and not refreeze:
        existing = {str(r["item_id"]): str(r["split"]) for r in read_jsonl(ITEMS_MANIFEST)}
    lock_old = load_lock()
    split_in = [SplitItem(i.item_id, i.label, i.domain_hmac, i.first_seen) for i in items]
    assigned, temporal = assign_splits(split_in, seed, existing)
    if existing and lock_old is not None:
        temporal = bool(lock_old.get("temporal_cut", False))
    items = [Item(**{**asdict(i), "split": assigned[i.item_id]}) for i in items]
    pub = [{k: v for k, v in asdict(i).items() if k in PUBLIC_FIELDS} for i in items]
    pub.sort(key=lambda r: str(r["item_id"]))
    lock = make_lock(pub, seed, temporal)
    if lock_old is not None and not refreeze and lock_old["test_sha256"] != lock["test_sha256"]:
        raise SystemExit("refusing: the frozen test split would change (use --refreeze-test and explain it in the PR)")
    errs = check_rows(pub, lock)
    if errs:
        raise SystemExit("; ".join(errs))
    write_jsonl(ITEMS_MANIFEST, pub)
    SPLITS_LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    priv = items_path()
    write_jsonl(priv, [asdict(i) for i in sorted(items, key=lambda i: i.item_id)])
    return items, lock


def load_private_items() -> list[Item]:
    return [Item(**r) for r in read_jsonl(items_path())]  # type: ignore[arg-type]


class CacheMismatch(RuntimeError):
    """The private item cache disagrees with the public manifest (e.g. a relabelled test item)."""


def verify_private_items(items: list[Item], rows: list[dict[str, object]]) -> None:
    """Every cached item must match the manifest row of the same id on split, label and domain; no extras."""
    by_id = {str(r["item_id"]): r for r in rows}
    seen = set()
    for i in items:
        r = by_id.get(i.item_id)
        if r is None:
            raise CacheMismatch("private cache holds an item that is not in the public manifest")
        if (r["split"], r["label"], r["domain_hmac"]) != (i.split, i.label, i.domain_hmac):
            raise CacheMismatch("private cache split/label/domain disagrees with the public manifest")
        seen.add(i.item_id)
    if seen != set(by_id):
        raise CacheMismatch("private cache is missing manifest items: rerun evals.datasets.build")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--refreeze-test", action="store_true", help="discard the existing split and lock (explain in PR)")
    args = ap.parse_args(argv)
    items, lock = build(args.seed, args.refreeze_test)
    print(f"items={len(items)} counts={lock['counts']} temporal_cut={lock['temporal_cut']}")
    zd = sum(1 for i in items if i.zero_day)
    print(f"zero_day_items={zd} (EVALS target >= 40)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
