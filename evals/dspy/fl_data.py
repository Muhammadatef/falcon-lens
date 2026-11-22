"""Deterministic dataset builders for the DSPy runs. Train/val only: nothing here reads the frozen test split.

* Incidents: Sentinel replay fixtures over many seeds. Planted campaign / kit reuse / reputation flip are kept
  (noise-only incidents are not labelled by the fixture and are skipped). Seeds also thin the campaign (drop 0 or
  1 lookalike domain) so counts vary. Gold facts come from the replayed incident, which the fixture labels confirm
  (type + event overlap), never from a model. Splits are by seed, so no fixture stream is in both splits.
* Messages: fl_messages templates (or an approved JSONL when present). Split by template.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from fl_messages import build_messages
from fl_metrics import SCRIPT_CATEGORIES, gold_facts

APPROVED_MESSAGES = Path(__file__).with_name("approved_messages.jsonl")


def dataset_hash(items: list[dict[str, Any]]) -> str:
    blob = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ------------------------------------------------------------------ incidents


def _ensure_sentinel_path() -> None:
    root = Path(__file__).resolve().parents[2] / "services" / "sentinel"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def incident_items_for_seed(seed: int) -> list[dict[str, Any]]:
    _ensure_sentinel_path()
    from sentinel_core.events import parse_event
    from sentinel_core.fixtures import generate
    from sentinel_core.replay import replay

    from falcon_sentinel.graph import evidence_view

    fx = generate(seed)
    rng = random.Random(f"dspy-incidents-{seed}")
    camp = next(x for x in fx.labels["incidents"] if x["type"] == "campaign")
    camp_ids = set(camp["event_ids"])
    camp_domains = sorted(
        {
            e["payload"]["domain_defanged"].replace("[.]", ".")
            for e in fx.events
            if e["event_id"] in camp_ids and e["type"] == "domain.observed"
        }
    )
    drop = {rng.choice(camp_domains)} if rng.random() < 0.5 else set()
    events = [
        e
        for e in fx.events
        if not (e["event_id"] in camp_ids and (e["payload"].get("domain_defanged", "").replace("[.]", ".") in drop))
        and not (e["event_id"] in camp_ids and e["payload"].get("registrable_domain") in drop)
    ]
    store = replay([parse_event(e) for e in events], vectors=fx.vectors)
    out: list[dict[str, Any]] = []
    for inc in store.all():
        ev_ids = {t["event_id"] for t in inc["timeline"] if "event_id" in t}
        label = next(
            (x for x in fx.labels["incidents"] if x["type"] == inc["type"] and ev_ids & set(x["event_ids"])), None
        )
        if label is None:
            continue
        view = evidence_view(inc)
        out.append({"id": f"inc-{seed}-{inc['type']}", "seed": seed, "view": view, "gold": gold_facts(view)})
    return out


def build_incident_dataset(
    train_seeds: range | list[int] = range(1, 13), val_seeds: range | list[int] = range(101, 109)
) -> dict[str, list[dict[str, Any]]]:
    if set(train_seeds) & set(val_seeds):
        raise ValueError("train and val seeds overlap")
    return {
        "train": [i for s in train_seeds for i in incident_items_for_seed(s)],
        "val": [i for s in val_seeds for i in incident_items_for_seed(s)],
    }


# ------------------------------------------------------------------ messages

_URL = re.compile(r"hxxps?://\S+", re.I)
_NUM = re.compile(r"\d{4,}")
_TOKEN = re.compile(r"[\w؀-ۿ]+")
_ARABIC = re.compile(r"[؀-ۿ]")


def redact(text: str) -> str:
    """No raw PII reaches the model: links and long digit runs (codes, ids) are replaced by placeholders."""
    return _NUM.sub("<NUM>", _URL.sub("<URL>", text))


def message_features(text: str) -> dict[str, Any]:
    letters = [c for c in text if c.isalpha()]
    return {
        "arabic_ratio": round(sum(bool(_ARABIC.match(c)) for c in letters) / len(letters), 2) if letters else 0.0,
        "has_link": bool(_URL.search(text)),
        "has_code": bool(_NUM.search(text)),
        "length": len(text),
    }


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(redact(text).lower()))


def nearest_scripts(
    text: str, library: list[dict[str, Any]], exclude_id: str | None = None, k: int = 3
) -> list[dict[str, Any]]:
    """Top-k labelled scripts by token Jaccard (stand-in for the pgvector kNN, which needs the embedder)."""
    q = _tokens(text)
    scored = []
    for it in library:
        if it["id"] == exclude_id:
            continue
        t = _tokens(it["text"])
        sim = len(q & t) / len(q | t) if q | t else 0.0
        scored.append((sim, it["id"], it["category"]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"label": c, "similarity": round(s, 2)} for s, _, c in scored[:k]]


def load_messages() -> tuple[list[dict[str, Any]], str]:
    if APPROVED_MESSAGES.exists():
        rows = [json.loads(line) for line in APPROVED_MESSAGES.read_text().splitlines() if line.strip()]
        return rows, "approved_messages.jsonl"
    return build_messages(), "fl_messages.templates"


def build_message_dataset(max_train: int = 72, max_val: int = 54, seed: int = 7) -> dict[str, list[dict[str, Any]]]:
    rows, _src = load_messages()
    for r in rows:
        if r["category"] not in SCRIPT_CATEGORIES:
            raise ValueError(f"unknown category {r['category']}")
    # group split: the third template of every (category, language) cell is validation-only
    val_rows = [r for r in rows if r["template"].endswith("/2")]
    train_rows = [r for r in rows if not r["template"].endswith("/2")]
    rng = random.Random(seed)

    def pick(pool: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
        pool = sorted(pool, key=lambda r: r["id"])
        rng.shuffle(pool)
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for r in pool:  # stratify by category, round-robin
            by_cat.setdefault(r["category"], []).append(r)
        chosen: list[dict[str, Any]] = []
        while len(chosen) < n and any(by_cat.values()):
            for c in sorted(by_cat):
                if by_cat[c] and len(chosen) < n:
                    chosen.append(by_cat[c].pop())
        return sorted(chosen, key=lambda r: r["id"])

    train, val = pick(train_rows, max_train), pick(val_rows, max_val)
    out: dict[str, list[dict[str, Any]]] = {}
    for name, part in (("train", train), ("val", val)):
        items = []
        for r in part:
            items.append(
                {
                    "id": r["id"],
                    "message": redact(r["text"]),
                    "features": message_features(r["text"]),
                    # the script library is the TRAIN pool only (leave-one-out for train items): no val leakage
                    "nearest": nearest_scripts(r["text"], train, exclude_id=r["id"]),
                    "gold_category": r["category"],
                    "gold_is_scam": r["category"] != "none",
                    "language": r["language"],
                    "synthetic": True,
                }
            )
        out[name] = items
    return out
