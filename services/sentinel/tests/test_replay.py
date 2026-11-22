from __future__ import annotations

import json

import pytest
from jsonschema import Draft202012Validator
from sentinel_core.events import INCIDENT_SCHEMA_PATH, EventValidationError, find_raw_text, parse_event
from sentinel_core.fixtures import generate
from sentinel_core.incidents import InMemoryIncidentStore, Sentinel, validate_incident
from sentinel_core.replay import load_jsonl, replay


@pytest.fixture(scope="module")
def fx():
    return generate()


def run(fx, times=1):
    events = [parse_event(e) for e in fx.events]
    s = Sentinel(InMemoryIncidentStore(), vectors=fx.vectors)
    for _ in range(times):
        s.process(events)
    return s.store.all()


def test_fixture_is_deterministic_and_replay_labelled(fx):
    assert generate().events == fx.events
    assert {e["source"] for e in fx.events} == {"replay"}
    assert all(parse_event(e) for e in fx.events)
    text = json.dumps(fx.events)
    assert all(".test" in d for d in [text]) and "http" not in text


def test_planted_stream_yields_exactly_one_campaign_even_replayed_twice(fx):
    once, twice = run(fx, 1), run(fx, 2)
    assert once == twice
    camps = [i for i in twice if i["type"] == "campaign"]
    assert len(camps) == 1
    assert camps[0]["rule_ids"] == ["R1", "R2"] and camps[0]["brand_id"] == "falcon_demo_bank"
    assert camps[0]["severity"] == "high" and camps[0]["source"] == "replay"


def test_incidents_match_labels_and_nothing_else(fx):
    incs = run(fx)
    assert len(incs) == len(fx.labels["incidents"]) == 3
    for lab in fx.labels["incidents"]:
        (inc,) = [i for i in incs if i["type"] == lab["type"]]
        assert inc["rule_ids"] == lab["rule_ids"]
        assert sorted(t["event_id"] for t in inc["timeline"] if "event_id" in t) == lab["event_ids"]


def test_replay_order_independent(fx):
    events = [parse_event(e) for e in fx.events]
    a = Sentinel(InMemoryIncidentStore(), vectors=fx.vectors)
    a.process(list(reversed(events)))
    assert a.store.all() == run(fx)


def test_incident_ids_stable_across_fresh_stores(fx):
    assert [i["incident_id"] for i in run(fx)] == [i["incident_id"] for i in run(fx)]


def test_incidents_validate_against_contract_and_have_no_raw_text(fx):
    schema = Draft202012Validator(json.loads(INCIDENT_SCHEMA_PATH.read_text()))
    for inc in run(fx):
        schema.validate(inc)
        validate_incident(inc)
        assert inc["incident_id"].startswith("inc_") and len(inc["incident_id"]) == 30
        assert find_raw_text(inc) is None
        assert all("[.]" in i["value_defanged"] for i in inc["indicators"] if i["kind"] == "domain")
        assert "http" not in json.dumps(inc)


def test_raw_text_and_bad_events_rejected(fx):
    bad = dict(fx.events[0], payload={"verdict": "dangerous", "body": "hello"})
    with pytest.raises(EventValidationError):
        parse_event(bad)
    with pytest.raises(EventValidationError):
        parse_event(dict(fx.events[0], source="prod"))
    with pytest.raises(EventValidationError):
        parse_event(dict(fx.events[0], event_id="evt_short"))


def test_jsonl_roundtrip_and_replay(fx, tmp_path):
    p = tmp_path / "s.jsonl"
    fx.to_jsonl(p)
    events, errs = load_jsonl(p)
    assert errs == [] and len(events) == len(fx.events)
    store = replay(events, vectors=fx.vectors)
    assert len(store.all()) == 3
    p.write_text(p.read_text() + "{not json}\n")
    with pytest.raises(EventValidationError):
        load_jsonl(p)
    _, errs = load_jsonl(p, strict=False)
    assert len(errs) == 1
