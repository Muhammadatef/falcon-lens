"""Message-text eval: dataset hygiene, deterministic splits, frozen test lock, interval maths, audit sample size."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from evals.message_text import data
from evals.message_text.audit_sample import FRACTION, MIN_N, sample
from evals.message_text.run import wilson


def test_every_item_is_synthetic_and_defensive() -> None:
    rows = data.load_all()
    assert len(rows) >= 150
    for r in rows:
        assert r["synthetic"] is True
        assert not re.search(r"https?:|www\.|hxxp|\.com\b|\.ae\b|\[\.\]", r["text"], re.I), r["id"]
        assert not re.search(r"\b\d{9,}\b", r["text"].replace("0500000000", "")), r["id"]
        assert not re.search(r"\bsafe\b|آمن", r["text"], re.I) or r["label"] == "legitimate"
    assert len({r["text"] for r in rows}) == len(rows)


def test_dataset_has_hard_negatives_in_every_language() -> None:
    rows = data.load_all()
    for lang in ("gulf_arabic", "msa", "english", "arabizi"):
        assert any(r["language"] == lang and r["label"] == "scam" for r in rows)
        assert any(r["language"] == lang and r["label"] == "legitimate" for r in rows)
    subs = {r["subtype"] for r in rows if r["label"] == "legitimate"}
    assert {
        "otp_notice_never_share",
        "appointment_reminder",
        "delivery_update_no_payment",
        "family_friend_chat",
    } <= subs


def test_split_is_deterministic_and_covers_all() -> None:
    a = {r["id"]: r["split"] for r in data.load_all()}
    assert a == {r["id"]: r["split"] for r in data.load_all()}
    assert set(a.values()) <= {"train", "val", "test"}
    assert all(data.items(s) for s in ("train", "val", "test"))


def test_frozen_test_lock_verifies_and_detects_edits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert data.check_lock() == []
    lock = json.loads(data.LOCK.read_text())
    assert lock["n_test"] == len(data.items("test"))
    # a changed test text is caught
    rows = data.load_all()
    victim = next(r for r in rows if r["split"] == "test")
    monkeypatch.setattr(
        data, "load_all", lambda: [{**r, "text": r["text"] + "!"} if r["id"] == victim["id"] else r for r in rows]
    )
    assert any("changed" in e for e in data.check_lock())


def test_wilson_interval() -> None:
    w = wilson(0, 15)
    assert w["value"] == 0.0 and w["ci_low"] == 0.0 and 0.18 < w["ci_high"] < 0.23
    w = wilson(22, 26)
    assert w["ci_low"] < w["value"] < w["ci_high"]
    assert wilson(0, 0)["value"] is None


def test_audit_sample_meets_supervisor_minimums() -> None:
    rows = data.load_all()
    s = sample(rows)
    assert len(s) >= MIN_N and len(s) >= FRACTION * len(rows)
    assert s == sample(rows)  # seeded
    assert {r["label"] for r in s} == {"scam", "legitimate"}
