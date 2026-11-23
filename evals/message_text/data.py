"""Message-text eval data: load, deterministic split, frozen test lock.

Items are SYNTHETIC (synthetic=true), Falcon Demo Bank or generic roles only, no links, invented phone 0500000000.
Files: ``hand.jsonl`` (written by hand) and ``reviewed.jsonl`` (local-model drafts kept after hand review).
Split = sha256(id) bucket: <60 train, <80 val, else test. ``splits.lock`` freezes the test ids (and the sha256 of each
test text); ``check_lock`` fails if a test item changed or vanished, and a NEW id that hashes to test is refused
after the freeze (it is excluded, never added to test).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
FILES = ("hand.jsonl", "reviewed.jsonl", "hard_neg.jsonl")
LOCK = HERE / "splits.lock"


def bucket(item_id: str) -> int:
    return int(hashlib.sha256(item_id.encode()).hexdigest(), 16) % 100


def split_of(item_id: str) -> str:
    b = bucket(item_id)
    return "train" if b < 60 else "val" if b < 80 else "test"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_all() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in FILES:
        p = HERE / name
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("synthetic") is not True or r["label"] not in ("scam", "legitimate"):
                    raise ValueError(f"{name}: bad item {r.get('id')}")
                rows.append(r)
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids")
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else None
    frozen = set(lock["test"]) if lock else None
    out = []
    for r in rows:
        s = split_of(r["id"])
        if frozen is not None:
            if r["id"] in frozen:
                s = "test"
            elif s == "test":
                s = "excluded"  # new item hashing to test after the freeze
        out.append({**r, "split": s})
    return out


def items(split: str) -> list[dict[str, Any]]:
    return [r for r in load_all() if r["split"] == split]


def dataset_hash() -> str:
    h = hashlib.sha256()
    for r in sorted(load_all(), key=lambda x: x["id"]):
        h.update(f"{r['id']}|{r['label']}|{sha(r['text'])}\n".encode())
    return h.hexdigest()


def write_lock() -> dict[str, Any]:
    if LOCK.exists():
        raise SystemExit("splits.lock exists: the test split is frozen")
    t = {r["id"]: sha(r["text"]) for r in load_all() if r["split"] == "test"}
    lock = {"rule": "sha256(id)%100 >= 80", "n_test": len(t), "test": sorted(t), "text_sha256": t}
    LOCK.write_text(json.dumps(lock, indent=1) + "\n")
    return lock


def check_lock() -> list[str]:
    if not LOCK.exists():
        return ["splits.lock missing"]
    lock = json.loads(LOCK.read_text())
    cur = {r["id"]: r for r in load_all()}
    errs = []
    for i, h in lock["text_sha256"].items():
        if i not in cur:
            errs.append(f"test item {i} removed")
        elif sha(cur[i]["text"]) != h:
            errs.append(f"test item {i} changed")
        elif cur[i]["split"] != "test":
            errs.append(f"test item {i} moved")
    return errs
