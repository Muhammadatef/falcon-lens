"""R6 early_warning + incident `detection` (HUNTER.md sections 3-4), via the add-sentinel-rule pattern:
fire, no-fire and replay. Events carry `origin` as the consumer sets it from its own hunt_candidates table."""

from __future__ import annotations

from typing import Any

from factories import T0, ev, verdict_ev
from sentinel_core.events import Event
from sentinel_core.incidents import InMemoryIncidentStore, Sentinel, detection_block

DOM = "falcon-demo-bank-secure.test"


def hunt(
    domain: str, minutes: float, verdict: str = "dangerous", lookalike: bool = True, key: str | None = None
) -> Event:
    e = verdict_ev(domain, minutes, verdict=verdict, brand=None, key=key or f"h|{domain}|{minutes}", channel="hunt")
    e.payload.update({"origin": "hunt", "hunt_lookalike": lookalike, "hunt_brand_id": "falcon_demo_bank"})
    return e


def user(domain: str, minutes: float, verdict: str = "dangerous") -> Event:
    return verdict_ev(
        domain, minutes, verdict=verdict, brand="falcon_demo_bank", key=f"u|{domain}|{minutes}", channel="web"
    )


def run(events: list[Event]) -> list[dict[str, Any]]:
    s = Sentinel(InMemoryIncidentStore(), official_domains=["falcon-demo-bank.test"])
    s.process(events)
    return s.store.all()


def test_r6_fires_on_one_hunt_dangerous_lookalike() -> None:
    incs = run([hunt(DOM, 0)])
    assert len(incs) == 1
    inc = incs[0]
    assert inc["type"] == "early_warning" and inc["rule_ids"] == ["R6"] and inc["severity"] == "medium"
    assert inc["detection"] == {
        "origin": "hunt",
        "found_before_report": True,
        "first_hunt_seen": T0.isoformat().replace("+00:00", "Z"),
        "first_user_seen": None,
    }
    assert inc["indicators"][0]["found_by"] == "hunt"
    assert inc["channels"] == ["hunt"]


def test_r6_lookalike_by_construction_for_names_the_skeleton_misses() -> None:
    # A homoglyph (punycode) look-alike: the brand-id skeleton test cannot see it, the hunt table can.
    incs = run([hunt("xn--flcon-demo-bank-vcg.test", 0)])
    assert [i["type"] for i in incs] == ["early_warning"]


def test_r6_no_fire() -> None:
    assert run([hunt(DOM, 0, verdict="suspicious")]) == []  # suspicious alone opens nothing
    assert [i for i in run([user(DOM, 0)]) if i["type"] == "early_warning"] == []  # a person's check
    assert run([hunt("unrelated-shop.test", 0, lookalike=False)]) == []  # hunt origin, not a look-alike
    assert run([]) == []  # a never-scored candidate emits no event, so nothing can open


def test_spoofed_channel_without_origin_is_a_user_check() -> None:
    e = verdict_ev(DOM, 0, brand="falcon_demo_bank", channel="hunt")  # label only, no table match
    assert [i for i in run([e]) if i["type"] == "early_warning"] == []


def test_r6_replay_idempotent_and_order_independent() -> None:
    events = [hunt(DOM, 0), hunt("falcon-demo-bank-pay.test", 5), user("falcon-demo-bank-pay.test", 30)]
    a = run(events)
    b = run(list(reversed(events)))
    s = Sentinel(InMemoryIncidentStore(), official_domains=["falcon-demo-bank.test"])
    s.process(events)
    s.process(events)
    assert a == b == s.store.all()
    assert len([i for i in a if i["type"] == "early_warning"]) == 2


def test_found_before_report_false_when_user_older() -> None:
    incs = run([user(DOM, 0, verdict="suspicious"), hunt(DOM, 10)])
    ew = [i for i in incs if i["type"] == "early_warning"][0]
    assert ew["detection"]["found_before_report"] is False
    assert ew["detection"]["origin"] == "mixed"
    assert ew["indicators"][0]["found_by"] == "user"


def test_report_older_than_hunt_counts_as_user() -> None:
    first = user(DOM, 0, verdict="suspicious")
    rep = ev("report.submitted", 1, {"kind": "scam", "verdict_id": first.verdict_id}, "r1", vid=first.verdict_id)
    incs = run([first, rep, hunt(DOM, 10)])
    ew = [i for i in incs if i["type"] == "early_warning"][0]
    assert ew["detection"]["found_before_report"] is False


def test_user_after_hunt_keeps_found_before_report() -> None:
    incs = run([hunt(DOM, 0), user(DOM, 30)])
    ew = [i for i in incs if i["type"] == "early_warning"][0]
    assert ew["detection"]["found_before_report"] is True
    assert ew["detection"]["origin"] == "mixed" and ew["detection"]["first_user_seen"] is not None


def test_found_before_report_never_flips_back() -> None:
    firsts = {DOM: (T0, None)}
    assert detection_block([DOM], firsts, None)["found_before_report"] is True  # type: ignore[index]
    old = {
        "detection": {"origin": "mixed", "found_before_report": False, "first_hunt_seen": None, "first_user_seen": None}
    }
    assert detection_block([DOM], firsts, old)["found_before_report"] is False  # type: ignore[index]
    assert detection_block([DOM], {DOM: (None, T0)}, None) is None  # hunt saw none of it: no block


def test_old_incidents_get_no_detection_block() -> None:
    incs = run([user(f"falcon-demo-bank-{w}.test", i) for i, w in enumerate(("pay", "login", "fine"))])
    assert incs and all("detection" not in i for i in incs)
