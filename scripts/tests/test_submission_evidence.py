"""scripts/submission/evidence.py: the other artifact families are read from files, never typed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from submission import check_numbers, evidence  # noqa: E402


def _write(root: Path, rel: str, data: dict) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _redteam(budget: str, ran: int, stamp: str) -> dict:
    return {
        "llm_budget": budget,
        "generated_at": stamp,
        "summary": {"overall": {"cases": 10, "harmful": 0, "ci95": [0.0, 0.25], "llm_ran": ran}},
    }


def test_redteam_line_states_answered_next_to_harmful(tmp_path: Path) -> None:
    _write(tmp_path, "redteam/redteam_a_20261124T010000Z.json", _redteam("production", 3, "2026-11-24T01:00:00Z"))
    _write(tmp_path, "redteam/redteam_b_20261124T020000Z.json", _redteam("production", 7, "2026-11-24T02:00:00Z"))
    ev = evidence.load(tmp_path)
    line = ev.redteam_line("production")
    assert line is not None
    assert "harmful 0 of 10" in line
    assert "answering 7 of 10" in line  # the newest run of that budget wins


def test_fp_history_is_oldest_first_and_newest_is_not_assumed_best(tmp_path: Path) -> None:
    for name, created, value in (
        ("a.json", "2026-11-23T01:00:00Z", 0.3),
        ("b.json", "2026-11-23T02:00:00Z", 0.1),
        ("c.json", "2026-11-23T03:00:00Z", 0.2),
    ):
        _write(
            tmp_path,
            f"fp_regress/{name}",
            {
                "created_at": created,
                "false_positive_rate": {"value": value, "ci95": [0.0, 0.5]},
                "n": 200,
                "target": 0.02,
            },
        )
    line = evidence.load(tmp_path).fp_history_line()
    assert line is not None
    assert "first run 30.0%" in line and "lowest 10.0%" in line and "newest 20.0%" in line
    assert "the target is not met" in line


def test_still_not_measured_drops_superseded_keys_only_when_the_family_exists(tmp_path: Path) -> None:
    keys = ["injection_attack_success_rate", "arabic_clarity", "something_else"]
    assert evidence.still_not_measured(keys, tmp_path) == keys
    _write(tmp_path, "redteam/redteam_a_20261124T010000Z.json", _redteam("production", 3, "x"))
    _write(tmp_path, "arabic_clarity/arabic_clarity_x_20261123T140938Z.json", {"area": "arabic_clarity"})
    assert evidence.still_not_measured(keys, tmp_path) == ["arabic_clarity_human_rating", "something_else"]


def test_numbers_of_other_families_are_traceable(tmp_path: Path) -> None:
    _write(tmp_path, "redteam/redteam_a_20261124T010000Z.json", _redteam("production", 7, "2026-11-24T01:00:00Z"))
    traceable = check_numbers.Traceable(None, more=tuple(evidence.load(tmp_path).sources()))
    assert traceable.has_number("7")
    assert traceable.has_number("25.0%")
    assert not traceable.has_number("8")
