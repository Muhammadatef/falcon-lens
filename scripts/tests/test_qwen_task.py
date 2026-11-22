"""Offline tests for scripts/qwen_task.py helpers (no model calls).

Run: uv run --no-project --with httpx --with jsonschema --with pytest pytest scripts/test_qwen_task.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qwen_task as q


def test_normalise_arabic_variants_match() -> None:
    assert q.normalise("أهلاً  وسهلاً!") == q.normalise("اهلا وسهلا")


def test_jaccard_near_duplicate() -> None:
    a = q.shingles("Your parcel is held. Pay AED 12 redelivery fee today")
    b = q.shingles("Your parcel is held!  Pay AED 12 redelivery fee today.")
    c = q.shingles("Falcon Demo Bank: never share your code with anyone")
    assert q.jaccard(a, b) >= 0.8
    assert q.jaccard(a, c) < 0.5


def test_plan_strata_sums_to_count() -> None:
    spec = {"count": 160, "strata": [{"share": 0.15}] * 4 + [{"share": 0.10}] * 4}
    plan = q.plan_strata(spec)
    assert sum(s["target"] for s in plan) == 160
    assert [s["target"] for s in plan[:4]] == [24] * 4


def test_parse_items_tolerates_garbage() -> None:
    assert q.parse_items("not json") == []
    assert q.parse_items('{"items": [{"a": 1}]}') == [{"a": 1}]
    assert q.parse_items('[{"a": 1}]') == [{"a": 1}]
