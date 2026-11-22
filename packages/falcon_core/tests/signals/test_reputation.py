import json
import logging
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from netfakes import _EVIDENCE_SCHEMA, NOW, Ctx, FakeHTTP, result, validate  # noqa: PLC2701

from falcon_core.security.http import FetchFailed, FetchFailReason
from falcon_core.signals import REGISTRY
from falcon_core.signals.base import Evidence
from falcon_core.signals.cache import MemoryCache
from falcon_core.signals.reputation import metrics
from falcon_core.signals.reputation.mirror import (
    FeedMirror,
    feed_updated_event,
    new_event_id,
    refresh_openphish,
    row_members,
    run_refresh_loop,
)

# Synthetic, non-resolving `.test` URLs only (RFC 2606). No real feed data in the repo.
BAD = "https://fake-bank-login.test/verify/account?id=1"
BAD_HOST_ONLY = "https://bare-host-phish.test/"
SHARED = "https://shared-host.test/user123/page"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("GOOGLE_SAFE_BROWSING_API_KEY", "URLHAUS_AUTH_KEY", "FL_FEED_OPENPHISH_ENABLED"):
        monkeypatch.delenv(k, raising=False)


async def run(name: str, ctx: Any) -> list[Evidence]:
    _spec, fn = REGISTRY[name]
    return await fn(ctx)


async def loaded_mirror(updated_at: float = NOW - 600) -> tuple[MemoryCache, FeedMirror]:
    kv = MemoryCache()
    m = FeedMirror(kv)
    members = row_members(BAD) + row_members(BAD_HOST_ONLY) + row_members(SHARED)
    await m.load(members, updated_at)
    return kv, m


def test_specs() -> None:
    assert REGISTRY["rep.openphish"][0].network == "local_mirror"
    assert REGISTRY["rep.openphish"][0].tier == "T0"
    assert REGISTRY["rep.gsb"][0].network == "egress_proxy"


async def test_mirror_exact_hit_fresh() -> None:
    _, m = await loaded_mirror()
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=m))
    validate([ev])
    assert ev.polarity == "risk" and ev.source == "openphish" and ev.tier == "T0"
    assert ev.observed["hit"] is True and ev.observed["match"] == "url"
    assert ev.observed["feed_age_s"] == 600 and ev.observed["fresh"] is True


async def test_mirror_hit_canonical_variants() -> None:
    _, m = await loaded_mirror()
    for u in (
        "HTTPS://Fake-Bank-Login.TEST/verify/account?id=1#frag",
        "https://fake-bank-login.test:443/verify/account?id=1",
    ):
        (ev,) = await run("rep.openphish", Ctx(url=u, mirror=m))
        assert ev.observed["hit"] is True, u


async def test_mirror_miss() -> None:
    _, m = await loaded_mirror()
    (ev,) = await run("rep.openphish", Ctx(url="https://clean-site.test/", mirror=m))
    assert ev.observed["hit"] is False and ev.polarity == "neutral" and ev.error is None


async def test_host_match_only_for_bare_path_listings() -> None:
    _, m = await loaded_mirror()
    (a,) = await run("rep.openphish", Ctx(url="https://bare-host-phish.test/other/path", mirror=m))
    assert a.observed["hit"] is True and a.observed["match"] == "host"
    # a path listed on a shared host must not condemn the host
    (b,) = await run("rep.openphish", Ctx(url="https://shared-host.test/someone-else", mirror=m))
    assert b.observed["hit"] is False


async def test_stale_mirror_marks_fresh_false() -> None:
    _, m = await loaded_mirror(updated_at=NOW - 7 * 3600)
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=m))
    assert ev.observed["hit"] is True and ev.observed["fresh"] is False
    assert ev.observed["feed_age_s"] == 7 * 3600


async def test_fresh_boundary_is_six_hours() -> None:
    _, m = await loaded_mirror(updated_at=NOW - 6 * 3600)
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=m))
    assert ev.observed["fresh"] is False  # age < 6 h required


async def test_unloaded_mirror_is_error() -> None:
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=FeedMirror(MemoryCache())))
    assert ev.error == "feed_unavailable"


async def test_openphish_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_FEED_OPENPHISH_ENABLED", "false")
    _, m = await loaded_mirror()
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=m))
    assert ev.error == "feed_disabled"
    assert metrics.FEED_ENABLED.labels(feed="openphish")._value.get() == 0


async def test_evidence_never_contains_url() -> None:
    _, m = await loaded_mirror()
    (ev,) = await run("rep.openphish", Ctx(url=BAD, mirror=m))
    blob = json.dumps(ev.to_dict())
    assert "fake-bank-login" not in blob and "verify" not in blob


async def test_no_url_in_logs(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    caplog.set_level(logging.DEBUG)
    _write_feed(tmp_path)
    await refresh_openphish(MemoryCache(), tmp_path, now=NOW)
    _, m = await loaded_mirror()
    await run("rep.openphish", Ctx(url=BAD, mirror=m))
    assert "fake-bank-login" not in caplog.text


# ------------------------------------------------------------ gsb / urlhaus


async def test_gsb_and_urlhaus_disabled_without_keys() -> None:
    http = FakeHTTP({})
    for name in ("rep.gsb", "rep.urlhaus"):
        (ev,) = await run(name, Ctx(url=BAD, http=http))
        validate([ev])
        assert ev.error == "feed_disabled" and ev.observed is None
    assert http.posts == [] and http.calls == []
    assert metrics.FEED_ENABLED.labels(feed="gsb")._value.get() == 0
    assert metrics.FEED_ENABLED.labels(feed="urlhaus")._value.get() == 0


async def test_gsb_hit_miss_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", "test-key")
    hit = {
        "matches": [
            {
                "threatType": "SOCIAL_ENGINEERING",
                "platformType": "ANY_PLATFORM",
                "threatEntryType": "URL",
                "threat": {"url": BAD},
            }
        ]
    }
    http = FakeHTTP({"https://safebrowsing.googleapis.com/v4/threatMatches:find": result(hit)})
    ctx = Ctx(url=BAD, http=http)
    (ev,) = await run("rep.gsb", ctx)
    validate([ev])
    assert ev.observed == {"hit": True, "feed": "gsb", "threat_types": ["SOCIAL_ENGINEERING"]}
    assert ev.polarity == "risk"
    body = http.posts[0][1]["json"]
    assert body["threatInfo"]["threatEntries"][0]["url"].startswith("https://fake-bank-login.test")
    assert metrics.FEED_ENABLED.labels(feed="gsb")._value.get() == 1
    await run("rep.gsb", ctx)
    assert len(http.posts) == 1  # cached

    miss = FakeHTTP({"https://safebrowsing.googleapis.com/": result("{}")})
    (ev2,) = await run("rep.gsb", Ctx(url="https://clean-site.test/", http=miss))
    assert ev2.observed["hit"] is False and ev2.error is None


async def test_gsb_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", "test-key")
    (ev,) = await run(
        "rep.gsb",
        Ctx(url=BAD, http=FakeHTTP({"https://safebrowsing": FetchFailed(FetchFailReason.TIMEOUT)})),
    )
    assert ev.error == "gsb_timeout"
    (ev,) = await run("rep.gsb", Ctx(url=BAD, http=object()))  # guarded client without POST support
    assert ev.error == "gsb_post_unsupported"


async def test_urlhaus_hit_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("URLHAUS_AUTH_KEY", "test-key")
    doc = {
        "query_status": "ok",
        "url_count": "2",
        "urls": [{"url_status": "online"}, {"url_status": "offline"}],
    }
    http = FakeHTTP({"https://urlhaus-api.abuse.ch/v1/host/": result(doc)})
    (ev,) = await run("rep.urlhaus", Ctx(url=BAD, http=http))
    validate([ev])
    assert ev.observed == {"hit": True, "feed": "urlhaus", "url_count": 2, "online": 1}
    assert http.posts[0][1]["headers"] == {"Auth-Key": "test-key"}
    assert http.posts[0][1]["data"] == {"host": "fake-bank-login.test"}
    none = FakeHTTP({"https://urlhaus-api.abuse.ch/": result({"query_status": "no_results"})})
    (ev2,) = await run("rep.urlhaus", Ctx(url="https://clean-site.test/", http=none))
    assert ev2.observed["hit"] is False


# ------------------------------------------------------------ refresh job


def _write_feed(d: Path, *, extra: list[dict[str, Any]] | None = None) -> None:
    import hashlib

    rows = []
    for u in (BAD, BAD_HOST_ONLY):
        rows.append(
            {
                "url": u,
                "first_seen": "2026-11-22T11:00:00Z",
                "feed_age": None,
                "sha256": hashlib.sha256(u.encode()).hexdigest(),
            }
        )
    rows.extend(extra or [])
    (d / "20261122.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + "\nnot json\n")
    (d / "snapshot_queue.jsonl").write_text(json.dumps({"url": "https://queue-only.test/", "sha256": "0" * 64}) + "\n")
    (d / "state.json").write_text(json.dumps({"last_poll_utc": "2026-11-22T11:00:00+00:00"}))


async def test_refresh_loads_mirror_sets_metrics_and_emits_event(tmp_path: Path) -> None:
    old = {
        "url": "https://ancient-phish.test/x",
        "first_seen": "2026-01-01T00:00:00Z",
        "sha256": "1" * 64,
    }
    _write_feed(tmp_path, extra=[old])
    kv = MemoryCache()
    events: list[dict[str, Any]] = []

    async def publish(ev: dict[str, Any]) -> None:
        events.append(ev)

    res = await refresh_openphish(kv, tmp_path, now=NOW, publish=publish)
    assert res.loaded and res.age_s == 3600 and res.rows == 2  # old row and bad line skipped
    assert await kv.scard("feed:openphish") == res.entries > 0
    assert metrics.FEED_AGE.labels(feed="openphish")._value.get() == 3600
    assert metrics.FEED_ENABLED.labels(feed="openphish")._value.get() == 1
    m = FeedMirror(kv)
    assert (await m.lookup(BAD)).match == "url"
    assert (await m.lookup("https://queue-only.test/")).match is None  # queue file ignored
    assert (await m.lookup("https://ancient-phish.test/x")).match is None
    (ev,) = events
    schema = json.loads((Path(__file__).parents[4] / "contracts" / "event.schema.json").read_text())
    jsonschema.validate(ev, schema)
    assert ev["type"] == "feed.updated" and ev["payload"] == {
        "feed": "openphish",
        "entries": res.entries,
        "age_s": 3600,
    }
    assert "fake-bank-login" not in json.dumps(ev)


async def test_refresh_without_files_does_not_load(tmp_path: Path) -> None:
    kv = MemoryCache()
    res = await refresh_openphish(kv, tmp_path, now=NOW)
    assert not res.loaded and await FeedMirror(kv).updated_at() is None
    res = await refresh_openphish(kv, tmp_path / "missing", now=NOW)
    assert not res.loaded


async def test_refresh_publish_failure_is_swallowed(tmp_path: Path) -> None:
    _write_feed(tmp_path)

    async def boom(_: dict[str, Any]) -> None:
        raise RuntimeError("bus down")

    res = await refresh_openphish(MemoryCache(), tmp_path, now=NOW, publish=boom)
    assert res.loaded


async def test_refresh_loop_runs_and_publishes_once_per_change(tmp_path: Path) -> None:
    import asyncio

    _write_feed(tmp_path)
    kv = MemoryCache()
    events: list[dict[str, Any]] = []

    async def publish(ev: dict[str, Any]) -> None:
        events.append(ev)

    task = asyncio.create_task(run_refresh_loop(kv, tmp_path, interval_s=0.01, publish=publish))
    await asyncio.sleep(0.15)
    task.cancel()
    assert await kv.scard("feed:openphish") > 0
    assert len(events) == 1


def test_event_id_matches_schema_pattern() -> None:
    import re

    assert re.fullmatch(r"evt_[0-9A-HJKMNP-TV-Z]{26}", new_event_id())
    ev = feed_updated_event("openphish", 3, 10, NOW)
    assert ev["occurred_at"].endswith("Z")


def test_evidence_schema_loaded() -> None:
    assert _EVIDENCE_SCHEMA["title"] == "Evidence"


def test_mirror_members_are_bare_sha256_hex() -> None:
    import hashlib
    import re

    members = row_members(BAD) + row_members(BAD_HOST_ONLY)
    assert all(re.fullmatch(r"[0-9a-f]{64}", m) for m in members)
    assert hashlib.sha256(b"bare-host-phish.test").hexdigest() in members
    assert hashlib.sha256(BAD.encode()).hexdigest() in members
