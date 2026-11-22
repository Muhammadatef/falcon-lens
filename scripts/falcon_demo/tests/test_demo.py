"""Generators: rates, labels, idempotency, and that the planted campaign really fires an incident."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from falcon_demo import corpus, ops, replay, seed
from falcon_demo.common import ApiClient, ApiError, Throttled, load_env, refang, retry_throttled, xadd_command
from sentinel_core.events import parse_event
from sentinel_core.replay import replay as sentinel_replay

START = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


class FakeSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def xadd_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def close(self) -> None:
        pass


class FakeClient:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, str | None]] = []
        self.fail = fail

    def check_url(self, url: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        if self.fail:
            raise self.fail
        self.calls.append(("url", url, idem))
        return {"verdict_id": f"vd_{len(self.calls)}", "verdict": "dangerous" if "bnak" in url else "no_warning_signs"}

    def check_message(self, text: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        self.calls.append(("message", text, idem))
        return {"verdict_id": f"vd_{len(self.calls)}"}


# ---- parsing ----------------------------------------------------------------------------------------------
def test_parse_rate_and_duration() -> None:
    assert replay.parse_rate("2/s") == 2.0
    assert replay.parse_rate("120/m") == 2.0
    assert replay.parse_rate("0.5") == 0.5
    assert replay.parse_duration("10m") == 600
    assert replay.parse_duration("1h30m") == 5400
    assert replay.parse_duration("90") == 90
    for bad in ("fast", "0/s", ""):
        with pytest.raises(ValueError):
            replay.parse_rate(bad)
    for bad in ("soon", "0s", "10x"):
        with pytest.raises(ValueError):
            replay.parse_duration(bad)


# ---- replay plan --------------------------------------------------------------------------------------------
def test_plan_rate_and_mix() -> None:
    plan = replay.build_plan(2.0, 600, START)
    urls = [c for c in plan if c.kind == "url"]
    assert len(urls) == 1200  # rate x duration
    assert max(c.t for c in urls) < 600
    gaps = {round(b.t - a.t, 6) for a, b in zip(urls, urls[1:], strict=False)}
    assert gaps == {0.5}  # steady
    mix = Counter(c.expect for c in urls)
    assert set(mix) == {"dangerous", "suspicious", "no_warning_signs"}
    assert all(v > 100 for v in mix.values())
    assert len({c.value for c in urls}) == len(urls)  # unique queries: no verdict-cache short circuit
    assert [c.t for c in plan] == sorted(c.t for c in plan)


def test_plan_is_deterministic_and_urls_are_reserved_tld() -> None:
    a = replay.build_plan(1.0, 60, START)
    b = replay.build_plan(1.0, 60, START)
    assert [(c.t, c.value, c.event) for c in a] == [(c.t, c.value, c.event) for c in b]
    for c in a:
        if c.kind == "url":
            assert ".test/" in c.value


def test_campaign_events_are_labelled_replay_valid_and_fire_an_incident() -> None:
    plan = replay.build_plan(1.0, 600, START)
    events = [c.event for c in plan if c.kind == "event" and c.event]
    assert len(events) == 8  # 4 domain.observed + 4 verdict.created
    assert {e["source"] for e in events} == {"replay"}
    parsed = [parse_event(e) for e in events]  # validates against contracts/event.schema.json, no raw text
    assert len({e.event_id for e in parsed}) == 8
    assert all(parsed[0].occurred_at <= e.occurred_at < START.replace(hour=13) for e in parsed)
    store = sentinel_replay(parsed)
    types = {i["type"] for i in store.all()}
    assert "campaign" in types
    assert all(i["source"] == "replay" for i in store.all())


def test_campaign_rekeyed_per_run_so_it_fires_again() -> None:
    later = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    e1 = {c.event["event_id"] for c in replay.build_plan(1.0, 600, START) if c.event}
    e2 = {c.event["event_id"] for c in replay.build_plan(1.0, 600, later) if c.event}
    assert not e1 & e2
    both = [parse_event(c.event) for p in (START, later) for c in replay.build_plan(1.0, 600, p) if c.event]
    assert sum(i["type"] == "campaign" for i in sentinel_replay(both).all()) >= 2


def test_run_plan_honours_schedule_and_labels() -> None:
    plan = replay.build_plan(2.0, 10, START)
    now = [0.0]
    slept: list[float] = []

    def sleep(d: float) -> None:
        slept.append(d)
        now[0] += d

    client, sink = FakeClient(), FakeSink()
    st = replay.run_plan(plan, client, sink, clock=lambda: now[0], sleep=sleep, workers=1)  # type: ignore[arg-type]
    assert st.checks == 20
    assert st.events == len(sink.events) == 8
    assert abs(sum(slept) - max(c.t for c in plan)) < 1e-6  # real-time pacing, nothing skipped
    assert all(e["source"] == "replay" for e in sink.events)


def test_run_plan_counts_throttling_without_crashing() -> None:
    plan = replay.build_plan(1.0, 3, START, campaign=False)
    st = replay.run_plan(plan, FakeClient(fail=Throttled(5)), None, clock=lambda: 1e9, sleep=lambda _: None)  # type: ignore[arg-type]
    assert st.throttled == 3 and st.checks == 0


# ---- seed ---------------------------------------------------------------------------------------------------
def test_fixture_corpus_is_fictional_only() -> None:
    items = corpus.fixture_items()
    assert any(i.expect == "dangerous" for i in items) and any(i.expect == "no_warning_signs" for i in items)
    for i in items:
        if i.kind == "url":
            assert i.value.split("/")[2].endswith(".test")


def test_seed_is_idempotent_and_sets_source_via_client() -> None:
    items = corpus.fixture_items()
    client, state = FakeClient(), {}
    s1 = seed.run_seed(items, client, None, state=state, rate_per_s=0, sleep=lambda _: None)  # type: ignore[arg-type]
    assert sum(s1.submitted.values()) == len(items) and not s1.skipped
    n_calls = len(client.calls)
    s2 = seed.run_seed(items, client, None, state=state, rate_per_s=0, sleep=lambda _: None)  # type: ignore[arg-type]
    assert sum(s2.skipped.values()) == len(items) and len(client.calls) == n_calls  # nothing resent
    s3 = seed.run_seed(items, client, None, state=state, force=True, rate_per_s=0, sleep=lambda _: None)  # type: ignore[arg-type]
    assert sum(s3.submitted.values()) == len(items)
    assert len({c[2] for c in client.calls}) == len(items)  # stable Idempotency-Key per item
    assert "seed summary" in s1.render()


def test_seed_state_roundtrip_and_progress(tmp_path: Path) -> None:
    p = tmp_path / "state.json"
    seed.save_state({"a": "vd_1"}, p)
    assert seed.load_state(p) == {"a": "vd_1"}
    assert seed.load_state(tmp_path / "missing.json") == {}
    assert seed.progress_bar(5, 10).endswith("5/10")


def test_seed_stops_when_api_is_down() -> None:
    items = corpus.fixture_items()
    s = seed.run_seed(items, FakeClient(fail=ApiError("API unreachable: ConnectError")), None, state={}, rate_per_s=0)  # type: ignore[arg-type]
    assert sum(s.failed.values()) == 1  # bails after the first failure instead of N errors


def test_seed_reports_verdict_mismatch() -> None:
    items = [corpus.Item("fixture", "url", "https://falcon-demo-bnak.test/login", "no_warning_signs")]
    s = seed.run_seed(items, FakeClient(), None, state={}, rate_per_s=0)  # type: ignore[arg-type]
    assert len(s.mismatches) == 1


def test_phishing_is_hashes_only_and_events_validate(tmp_path: Path) -> None:
    m = tmp_path / "m.jsonl"
    rows = [
        {"url_sha256": f"{i:064x}", "registrable_domain_sha256": f"{i + 1:064x}", "first_seen": "2026-11-22T11:56:59Z"}
        for i in range(5)
    ]
    m.write_text("".join(json.dumps(r) + "\n" for r in rows))
    items = corpus.phish_event_items(m, limit=None)
    assert len(items) == 5 and all(i.kind == "event" for i in items)
    for i in items:
        ev = corpus.hash_event(i)
        assert ev == corpus.hash_event(i)  # deterministic -> same event_id on re-seed
        assert ev["source"] == "replay"
        parse_event(ev)
        assert "http" not in json.dumps(ev)
    sink, state = FakeSink(), {}
    seed.run_seed(items, None, sink, state=state)
    seed.run_seed(items, None, sink, state=state)
    assert len(sink.events) == 5  # second run: all skipped


def test_missing_sources_degrade_to_empty(tmp_path: Path) -> None:
    assert corpus.legit_items(tmp_path / "nope.csv") == []
    assert corpus.message_items(tmp_path) == []
    assert corpus.phish_event_items(tmp_path / "nope.jsonl") == []


def test_legit_csv_is_refanged_and_sampled(tmp_path: Path) -> None:
    f = tmp_path / "l.csv"
    f.write_text("url,x\n" + "".join(f"hxxps://site{i}[.]example/,y\n" for i in range(100)))
    items = corpus.legit_items(f, limit=10)
    assert len(items) == 10 and items[0].value == "https://site0.example/"
    assert items == corpus.legit_items(f, limit=10)


def test_messages_loader(tmp_path: Path) -> None:
    (tmp_path / "synthetic_messages_v2.jsonl").write_text(
        json.dumps({"text": "hello", "label": "scam"}) + "\n" + json.dumps({"text": "hi", "label": "legit"}) + "\n"
    )
    items = corpus.message_items(tmp_path, limit=None)
    assert [i.expect for i in items] == ["dangerous", None]


# ---- plumbing -----------------------------------------------------------------------------------------------
def test_refang_and_xadd_quoting() -> None:
    assert refang("hxxps://a[.]b/x") == "https://a.b/x"
    ev = {"event_id": 'x"y\\z', "payload": {"k": "line\nbreak"}}
    cmd = xadd_command(ev)
    assert cmd.startswith('XADD fl:events MAXLEN ~ 100000 * event "') and cmd.endswith('"\n')
    assert cmd.count("\n") == 1  # JSON newlines stay escaped


def test_client_sends_replay_source_and_key() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(202, json={"verdict_id": "vd_1"})

    c = ApiClient(
        "https://localhost:1",
        "k",
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://localhost:1"),
    )
    c.check_url("https://falcon-demo-bank.test/", idem="i")
    assert seen["x-falcon-source"] == "replay" and seen["x-api-key"] == "k" and seen["idempotency-key"] == "i"


def test_429_retry_after_is_honoured() -> None:
    calls = [Throttled(7), Throttled(3)]
    slept: list[float] = []

    def fn() -> str:
        if calls:
            raise calls.pop(0)
        return "ok"

    assert retry_throttled(fn, sleep=slept.append) == "ok" and slept == [7, 3]


def test_load_env_overrides_and_strips_comments(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("FL_GATEWAY_PORT=9443   # note\nFL_GRAFANA_PORT=4000\n#x=1\n")
    env = load_env(f, {"FL_GRAFANA_PORT": "4001", "PATH": "/bin"})
    assert env == {"FL_GATEWAY_PORT": "9443", "FL_GRAFANA_PORT": "4001"}


# ---- ops ----------------------------------------------------------------------------------------------------
def test_urls_follow_remapped_ports() -> None:
    rows = dict(ops.url_table({"FL_GATEWAY_PORT": "9443", "FL_GRAFANA_PORT": "4000"}))
    assert rows["Web app"] == "https://localhost:9443/"
    assert sum(k.startswith("Grafana") for k in rows) == 6
    assert rows["Prometheus"].endswith(":9090")


def test_tunnel_command_and_url_parsing() -> None:
    cmd = ops.tunnel_command({"FL_GATEWAY_PORT": "9443"})
    assert cmd[:3] == ["cloudflared", "tunnel", "--no-autoupdate"]
    assert "https://localhost:9443" in cmd and "--no-tls-verify" in cmd
    assert cmd[cmd.index("--http-host-header") + 1] == "localhost"
    assert cmd[cmd.index("--origin-server-name") + 1] == "localhost"
    log = "INF |  https://quiet-river-1234.trycloudflare.com  |\nINF hxxps://api[.]cloudflare[.]com/x"
    assert ops.parse_tunnel_url(log) == "https://quiet-river-1234.trycloudflare.com"
    assert ops.parse_tunnel_url("nothing here") is None


def test_verify_tunnel_requires_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(200, text="", headers={"content-type": "text/plain"})

    monkeypatch.setattr(ops.httpx, "get", fake_get)
    assert ops.verify_tunnel("https://x.trycloudflare.com", attempts=2, sleep=lambda _: None) is False

    def good(url: str, timeout: float) -> httpx.Response:
        return httpx.Response(200, json={"api": "v1"})

    monkeypatch.setattr(ops.httpx, "get", good)
    assert ops.verify_tunnel("https://x.trycloudflare.com", attempts=1, sleep=lambda _: None) is True


def test_tunnel_stop_without_pid_file_touches_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ops, "TUNNEL_PID_FILE", tmp_path / "none.pid")
    msgs: list[str] = []
    assert ops.tunnel_stop(msgs.append) == 0 and "not touched" in msgs[0]
