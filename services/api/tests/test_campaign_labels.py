from __future__ import annotations

from typing import Any

import pytest

from falcon_api.intel import campaign_of


def _inc(source: str, *domains: str) -> dict[str, Any]:
    return {
        "incident_id": "inc_01TEST",
        "type": "campaign",
        "severity": "high",
        "brand_id": None,
        "created_at": "2026-11-24T10:00:00Z",
        "updated_at": "2026-11-24T10:05:00Z",
        "linked_verdicts": [],
        "source": source,
        "indicators": [{"kind": "domain", "value_defanged": d, "first_seen": "2026-11-24T10:00:00Z"} for d in domains],
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_ENV", "demo")
    monkeypatch.setenv("FL_SSRF_ALLOW_HOSTS", "falcon-demo-bank-secure.test,falcon-demo-bank-login.test")


def test_all_fixture_domains_read_as_fixture_not_live() -> None:
    card = campaign_of(_inc("live", "falcon-demo-bank-secure[.]test", "falcon-demo-bank-login[.]test"))
    assert card["source"] == "fixture"


def test_mixed_or_real_domains_stay_live_and_replay_stays_replay() -> None:
    assert campaign_of(_inc("live", "falcon-demo-bank-secure[.]test", "x-pay[.]example"))["source"] == "live"
    assert campaign_of(_inc("replay", "falcon-demo-bank-secure[.]test"))["source"] == "replay"


def test_shared_platform_suffix_is_not_counted_as_an_indicator() -> None:
    assert campaign_of(_inc("live", "pages[.]dev", "evil-login[.]pages[.]dev"))["count"] == 1
