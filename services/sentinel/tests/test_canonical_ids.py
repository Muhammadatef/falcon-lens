from __future__ import annotations

import random

import pytest
from factories import observed_ev
from sentinel_core.events import parse_event
from sentinel_core.fixtures import generate
from sentinel_core.incidents import InMemoryIncidentStore, Sentinel

FX = generate()
EVENTS = [parse_event(e) for e in FX.events]


def run_batch():
    s = Sentinel(InMemoryIncidentStore(), vectors=FX.vectors)
    s.process(EVENTS)
    return s.store.all()


def _sig(incs):
    return [(i["incident_id"], i["type"], i["rule_ids"], i["created_at"]) for i in incs]


def _events(inc):
    return {t["event_id"] for t in inc["timeline"] if "event_id" in t}


@pytest.mark.parametrize("seed", range(50))
def test_ids_canonical_under_shuffled_one_at_a_time_arrival(seed):
    baseline = run_batch()
    shuffled = EVENTS[:]
    random.Random(seed).shuffle(shuffled)
    s = Sentinel(InMemoryIncidentStore(), vectors=FX.vectors)
    for e in shuffled:
        s.process([e])
    got = s.store.all()
    assert _sig(got) == _sig(baseline)
    assert [_events(i) for i in got] == [_events(i) for i in baseline]


def test_published_id_kept_when_not_pristine():
    evs = [observed_ev(f"falcon-demo-bank-{i}.test", i * 10) for i in range(1, 4)]
    s = Sentinel(InMemoryIncidentStore(), vectors={})
    s.process(evs)
    (inc,) = s.store.all()
    inc["status"] = "triaging"  # the agent has started: the id is published
    s.store.put(inc)
    s.process([observed_ev("falcon-demo-bank-0.test", 0)])  # an earlier event arrives late
    (after,) = s.store.all()
    assert after["incident_id"] == inc["incident_id"] and after["status"] == "triaging"


def test_pristine_incident_rekeyed_with_alias():
    evs = [observed_ev(f"falcon-demo-bank-{i}.test", i * 10) for i in range(1, 4)]
    s = Sentinel(InMemoryIncidentStore(), vectors={})
    s.process(evs)
    (old,) = s.store.all()
    s.process([observed_ev("falcon-demo-bank-0.test", 0)])
    (new,) = s.store.all()
    assert new["incident_id"] != old["incident_id"]
    assert any(t["what"] == f"alias {old['incident_id']}" for t in new["timeline"])
