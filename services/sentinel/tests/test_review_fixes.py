from __future__ import annotations

from sentinel_core.correlate import extract, registrable_domain
from sentinel_core.events import parse_time
from sentinel_core.rules import evaluate, load_rules

from factories import observed_ev, verdict_ev

RULES = {r.id: r for r in load_rules()}
B = "falcon_demo_bank"


def fire(rule_id, events, vectors=None):
    return evaluate(RULES[rule_id], [extract(e) for e in events], vectors)


def test_r4_fires_with_step_in_between_once_per_flip():
    evs = [
        verdict_ev("a.test", 0, "no_warning_signs"),
        verdict_ev("a.test", 100, "suspicious"),
        verdict_ev("a.test", 200, "dangerous"),
        verdict_ev("a.test", 300, "dangerous", type_="verdict.upgraded"),
    ]
    (m,) = fire("R4", evs)  # the second dangerous event reuses the same flip
    assert [f.verdict for f in m.features] == ["no_warning_signs", "dangerous"]


def test_r4_previous_verdict_on_non_first_event():
    first = verdict_ev("b.test", 0, "suspicious")
    later = verdict_ev("b.test", 50, "dangerous", type_="verdict.upgraded")
    later.payload["previous_verdict"] = "no_warning_signs"
    assert len(fire("R4", [first, later])) == 1


def test_refang_strips_scheme_and_rejects_garbage():
    assert registrable_domain("http://falcon-demo-bank-x.test/a?b=1") == "falcon-demo-bank-x.test"
    assert registrable_domain("hxxps://evil[.]test:8080/x") == "evil.test"
    assert registrable_domain("not a host!") == ""
    assert registrable_domain("localhost") == ""


def test_events_without_domain_do_not_count_as_distinct_domains():
    evs = [verdict_ev(f"x{i}.test", i, simhash=5) for i in range(3)]
    for e in evs:
        del e.payload["registrable_domain"]
    assert not fire("R2", evs)


def test_r1_requires_new_domains_first_seen_within_window():
    old = [observed_ev("falcon-demo-bank-old.test", -3000)]
    fresh = [observed_ev(f"falcon-demo-bank-n{i}.test", i) for i in range(2)]
    stale_verdict = [verdict_ev("falcon-demo-bank-old.test", 10, brand=B)]
    assert not fire("R1", old + fresh + stale_verdict)  # old domain is not new: only 2 new
    assert fire("R1", fresh + [observed_ev("falcon-demo-bank-n2.test", 5)])


def test_z_timestamp_parses():
    assert parse_time("2026-11-20T08:00:00Z") == parse_time("2026-11-20T08:00:00+00:00")
