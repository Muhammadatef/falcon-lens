import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import openphish as op

T0 = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def test_rate_guard_refuses_early_and_allows_after(tmp_path):
    st = tmp_path / "state.json"
    op.check_rate_guard(st, T0)  # no state: ok
    st.write_text(json.dumps({"last_poll_utc": T0.isoformat()}))
    with pytest.raises(op.PollTooEarly):
        op.check_rate_guard(st, T0 + timedelta(hours=11, minutes=59))
    op.check_rate_guard(st, T0 + timedelta(hours=12))


def test_canonical():
    c = op.canonicalize("HTTPS://Evil.Example.COM:443/a.b?x=1#frag")
    assert c == "https://evil.example.com/a.b?x=1"
    assert op.canonicalize("ftp://x.test/") is None


def test_dedup_and_manifest(tmp_path):
    feed = tmp_path / "feed"
    man = tmp_path / "m.jsonl"
    text = "http://a.example.test/x\nhttp://A.example.test/x#f\nhttps://b.example.test/\nnot a url\n"
    assert op.process_feed(text, T0, feed, man) == 2
    later = T0 + timedelta(hours=12)
    assert op.process_feed(text + "http://c.example.test/\n", later, feed, man) == 1
    rows = [json.loads(x) for x in man.read_text().splitlines()]
    assert len(rows) == 3 and len({r["url_sha256"] for r in rows}) == 3
    for r in rows:
        assert set(r) == {"url_sha256", "registrable_domain_sha256", "first_seen", "feed"}
        assert r["first_seen"].endswith("Z")
    blob = man.read_text()
    assert "hx" + "xp" not in blob and "example" not in blob and "http" not in blob
    raw = [json.loads(x) for f in feed.glob("2*.jsonl") for x in f.read_text().splitlines()]
    assert all(r["first_seen"] for r in raw)


def test_registrable_domain_private_psl():
    assert op.registrable_domain("http://a.b.example.co.uk/") == "example.co.uk"
    assert op.registrable_domain("http://foo.github.io/") == "foo.github.io"


def test_rebuild_manifest_matches(tmp_path):
    feed = tmp_path / "feed"
    man = tmp_path / "m.jsonl"
    op.process_feed("http://a.example.test/x\nhttps://b.example.test/\n", T0, feed, man)
    before = man.read_text()
    assert op.rebuild_manifest(feed, man) == 2
    assert man.read_text() == before


def test_data_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FL_DATA_DIR", str(tmp_path))
    assert op.data_dir() == tmp_path




def _no_http(*a, **k):
    raise AssertionError("HTTP must not be called when the rate guard refuses")


def test_poll_refuses_before_http_and_main_returns_3(monkeypatch, tmp_path):
    import httpx

    now = datetime.now(UTC)
    (tmp_path / "state.json").write_text(json.dumps({"last_poll_utc": now.isoformat()}))
    monkeypatch.setattr(op, "FEED_DIR", tmp_path)
    monkeypatch.setattr(httpx, "stream", _no_http)
    monkeypatch.setattr(httpx, "get", _no_http)
    with pytest.raises(op.PollTooEarly):
        op.poll(now=now + timedelta(hours=1))
    assert op.main() == 3


def test_corrupt_state_is_distinct(tmp_path):
    st = tmp_path / "state.json"
    st.write_text("{not json")
    with pytest.raises(op.CorruptState):
        op.check_rate_guard(st, T0)
    st.write_text("{}")
    with pytest.raises(op.CorruptState):
        op.check_rate_guard(st, T0)
