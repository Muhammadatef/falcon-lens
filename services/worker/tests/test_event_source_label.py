from __future__ import annotations

from typing import Any

import pytest

from falcon_worker.events import verdict_created


def _doc(source: str) -> dict[str, Any]:
    return {
        "verdict_id": "vd_01HZZZZZZZZZZZZZZZZZZZZZZZ",
        "verdict": "likely_scam",
        "risk_score": 90,
        "input_type": "url",
        "tier_reached": "T1",
        "degraded": False,
        "evidence": [],
        "source": source,
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_ENV", "demo")
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", "falcon-demo-bank-secure.test")


def test_event_for_a_fixture_host_is_labelled_fixture() -> None:
    ev = verdict_created(_doc("live"), {"final_registrable_domain": "falcon-demo-bank-secure.test"})
    assert ev["source"] == "fixture"


def test_event_for_a_real_host_or_replay_keeps_its_source() -> None:
    assert verdict_created(_doc("live"), {"final_registrable_domain": "x-pay.example.com"})["source"] == "live"
    assert (
        verdict_created(_doc("replay"), {"final_registrable_domain": "falcon-demo-bank-secure.test"})["source"]
        == "replay"
    )
    assert verdict_created(_doc("live"), {})["source"] == "live"
