from __future__ import annotations

import pytest
from factories import feedback_ev, observed_ev, report_ev, verdict_ev
from sentinel_core.correlate import domain_pattern, extract, hamming, registrable_domain
from sentinel_core.incidents import InMemoryIncidentStore, Sentinel
from sentinel_core.rules import RuleConfigError, evaluate, load_rules

RULES = {r.id: r for r in load_rules()}
B = "falcon_demo_bank"


def fire(rule_id, events, vectors=None):
    return evaluate(RULES[rule_id], [extract(e) for e in events], vectors)


def test_rules_file_defines_r1_to_r5():
    assert list(RULES) == ["R1", "R2", "R3", "R4", "R5"]
    assert {r.type for r in RULES.values()} == {"campaign", "kit_reuse", "report_burst", "reputation_flip", "quality"}


def test_bad_rule_config_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("rules:\n  - {id: X, type: nope, detector: threshold, event_types: [], group_by: a, window_minutes: 1, severity_floor: low}\n")
    with pytest.raises(RuleConfigError):
        load_rules(p)


# ---- R1 campaign
def test_r1_fires_on_three_lookalikes_in_window():
    evs = [observed_ev(f"falcon-demo-bank-{s}.test", m) for s, m in [("a", 0), ("login", 20), ("pay", 59)]]
    (m,) = fire("R1", evs)
    assert m.rule.type == "campaign" and len(m.features) == 3


def test_r1_not_fire_two_domains_or_outside_window_or_other_brand():
    assert not fire("R1", [observed_ev("falcon-demo-bank-a.test", 0), observed_ev("falcon-demo-bank-b.test", 10)])
    spread = [observed_ev(f"falcon-demo-bank-{i}.test", i * 90) for i in range(3)]
    assert not fire("R1", spread)
    unrelated = [observed_ev(f"unrelated-{i}.test", i) for i in range(5)]
    assert not fire("R1", unrelated)


def test_r1_same_domain_counted_once_across_event_types():
    evs = [observed_ev("falcon-demo-bank-a.test", 0), verdict_ev("falcon-demo-bank-a.test", 2, brand=B),
           observed_ev("falcon-demo-bank-b.test", 5), verdict_ev("falcon-demo-bank-b.test", 7, brand=B)]
    assert not fire("R1", evs)


def test_r1_ignores_no_warning_signs_verdicts():
    evs = [verdict_ev(f"falcon-demo-bank-{i}.test", i, "no_warning_signs", brand=B) for i in range(4)]
    assert not fire("R1", evs)


# ---- R2 kit reuse
def test_r2_fires_one_simhash_three_domains_within_hamming_6():
    base = 0xABCDEF0123456789
    evs = [verdict_ev(f"kit-{i}.test", i * 100, simhash=base ^ (0b1111 << i)) for i in range(3)]
    assert max(hamming(base ^ (0b1111 << i), base ^ (0b1111 << j)) for i in range(3) for j in range(3)) <= 6
    (m,) = fire("R2", evs)
    assert m.rule.type == "kit_reuse"


def test_r2_not_fire_two_domains_distant_hash_or_one_domain_repeated():
    base = 0xABCDEF0123456789
    assert not fire("R2", [verdict_ev(f"kit-{i}.test", i, simhash=base) for i in range(2)])
    far = [verdict_ev(f"kit-{i}.test", i, simhash=base ^ (0xFFFF << (16 * i))) for i in range(3)]
    assert not fire("R2", far)
    assert not fire("R2", [verdict_ev("kit-0.test", i, simhash=base, key=f"k{i}") for i in range(4)])


# ---- R3 report burst
def test_r3_fires_five_reports_in_30_min_via_cosine_cluster():
    vecs = {"s1": [1.0, 0.0, 0.1], "s2": [0.98, 0.05, 0.1], "s3": [1.0, 0.02, 0.0], "z": [0.0, 1.0, 0.0]}
    evs = [report_ev(fp, i * 5, i) for i, fp in enumerate(["s1", "s2", "s3", "s1", "s2"])]
    (m,) = fire("R3", evs, vecs)
    assert len(m.features) == 5
    evs2 = evs[:4] + [report_ev("z", 20, 9)]  # dissimilar vector: only 4 in the cluster
    assert not fire("R3", evs2, vecs)


def test_r3_not_fire_four_reports_or_slow_reports():
    vecs = {"s1": [1.0, 0.0]}
    assert not fire("R3", [report_ev("s1", i, i) for i in range(4)], vecs)
    assert not fire("R3", [report_ev("s1", i * 40, i) for i in range(6)], vecs)


# ---- R4 flip
def test_r4_fires_on_flip_and_on_previous_verdict_field():
    evs = [verdict_ev("flip.test", 0, "no_warning_signs"), verdict_ev("flip.test", 600, "dangerous", type_="verdict.upgraded")]
    (m,) = fire("R4", evs)
    assert m.rule.type == "reputation_flip"
    up = verdict_ev("other.test", 5, "dangerous", type_="verdict.upgraded")
    up.payload["previous_verdict"] = "no_warning_signs"
    assert len(fire("R4", [up])) == 1


def test_r4_not_fire_other_transitions_or_stale_or_other_domain():
    assert not fire("R4", [verdict_ev("a.test", 0, "suspicious"), verdict_ev("a.test", 5, "dangerous")])
    assert not fire("R4", [verdict_ev("a.test", 0, "dangerous"), verdict_ev("a.test", 5, "no_warning_signs")])
    assert not fire("R4", [verdict_ev("a.test", 0, "no_warning_signs"), verdict_ev("b.test", 5, "dangerous")])
    assert not fire("R4", [verdict_ev("a.test", 0, "no_warning_signs"), verdict_ev("a.test", 60 * 24 * 40, "dangerous")])


# ---- R5 quality
def test_r5_fires_five_fp_one_signal():
    (m,) = fire("R5", [feedback_ev("domain.age", i * 10, i) for i in range(5)])
    assert m.rule.type == "quality"


def test_r5_not_fire_four_mixed_signals_wrong_kind_or_slow():
    assert not fire("R5", [feedback_ev("domain.age", i, i) for i in range(4)])
    assert not fire("R5", [feedback_ev(f"sig{i}", i, i) for i in range(6)])
    assert not fire("R5", [feedback_ev("domain.age", i, i, kind="helpful") for i in range(6)])
    assert not fire("R5", [feedback_ev("domain.age", i * 61, i) for i in range(6)])


# ---- correlation helpers
def test_domain_pattern_and_registrable():
    assert domain_pattern("falcon-demo-bank-login.test", B) == (True, "login")
    assert domain_pattern("falcondem0bank.test", B)[0]
    assert domain_pattern("falcondembank.test", B)[0]  # one-char typo
    assert not domain_pattern("falcon-demo-bank-x.test", B, frozenset({"falcon-demo-bank-x.test"}))[0]
    assert not domain_pattern("example.test", B)[0]
    assert registrable_domain("a.b.falcon[.]test") == "falcon.test"
    assert registrable_domain("x.gov.ae") == "x.gov.ae"


# ---- idempotence per rule
@pytest.mark.parametrize("rid", ["R1", "R2", "R3", "R4", "R5"])
def test_rule_replay_idempotent(rid):
    sets = {
        "R1": [observed_ev(f"falcon-demo-bank-{i}.test", i) for i in range(3)],
        "R2": [verdict_ev(f"kit-{i}.test", i, simhash=7) for i in range(3)],
        "R3": [report_ev("s1", i, i) for i in range(5)],
        "R4": [verdict_ev("f.test", 0, "no_warning_signs"), verdict_ev("f.test", 9, "dangerous")],
        "R5": [feedback_ev("x", i, i) for i in range(5)],
    }
    s = Sentinel(InMemoryIncidentStore(), vectors={"s1": [1.0]})
    s.process(sets[rid])
    first = s.store.all()
    s.process(sets[rid])
    s.process(list(reversed(sets[rid])))
    assert s.store.all() == first and len(first) == 1 and first[0]["rule_ids"] == [rid]
