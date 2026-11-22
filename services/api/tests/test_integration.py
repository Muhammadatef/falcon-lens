from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import fakeredis
import httpx
import jsonschema
import pytest
from fastapi import Depends, FastAPI, Header, HTTPException

import falcon_api.integration as integ
from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryAuditLog, MemoryKeyStore, refuse_default_secrets
from falcon_api.db import MemorySubmissionStore
from falcon_api.intel import SentinelClient
from falcon_api.webhooks import SignatureError, sign, verify
from falcon_core.config import Settings
from falcon_core.contracts.incident import Incident
from tests.conftest import OPERATOR_KEY, ROOT, SANDBOX_KEY, FakeStore, make_doc, make_settings

ULID = "0123456789ABCDEFGHJKMNPQRS"


def make_incident(n: int, *, typ: str = "campaign", status: str = "open") -> dict[str, Any]:
    iid = f"inc_{n:026d}".replace("0", "0")
    return {
        "incident_id": iid,
        "type": typ,
        "severity": "high",
        "status": status,
        "brand_id": "falcon_demo_bank",
        "rule_ids": ["R1"],
        "indicators": [
            {"kind": "domain", "value_defanged": f"falcon-demo-{n}[.]test", "first_seen": f"2026-11-22T0{n}:00:00Z"},
            {"kind": "domain", "value_defanged": f"falcon-demo-b{n}[.]test", "first_seen": f"2026-11-22T0{n}:30:00Z"},
        ],
        "linked_verdicts": [],
        "timeline": [{"at": f"2026-11-22T0{n}:00:00Z", "what": "opened", "what_en": "Opened", "what_ar": "فُتح"}],
        "actions": [
            {
                "action_id": "act_1",
                "tool": "draft_takedown",
                "mode": "external_draft",
                "status": "awaiting_approval",
                "args": {"recipient_kind": "registrar"},
                "draft": {"recipient_kind": "registrar", "subject": "s", "body_en": "b", "body_ar": "ب"},
                "evidence_ids": [],
                "approved_by": "someone",
            }
        ],
        "source": "synthetic",
        "created_at": f"2026-11-22T0{n}:00:00Z",
        "updated_at": f"2026-11-22T0{n}:45:00Z",
    }


def fake_sentinel(incidents: list[dict[str, Any]], calls: list[tuple[str, str, str]]) -> FastAPI:
    """Like the real sentinel: EVERY internal route requires X-Operator-Key (reads included)."""

    def gate(x_operator_key: str | None = Header(None)) -> None:
        if x_operator_key != OPERATOR_KEY:
            raise HTTPException(401, "operator key required")

    app = FastAPI(dependencies=[Depends(gate)])

    @app.get("/internal/incidents")
    async def lst() -> list[dict[str, Any]]:
        return incidents

    @app.get("/internal/incidents/{iid}")
    async def one(iid: str) -> dict[str, Any]:
        for i in incidents:
            if i["incident_id"] == iid:
                return i
        raise HTTPException(404)

    @app.post("/internal/incidents/{iid}/actions/{aid}/{verb}")
    async def decide(
        iid: str,
        aid: str,
        verb: str,
        x_operator_key: str | None = Header(None),
        x_operator_name: str | None = Header(None),
    ) -> dict[str, Any]:
        calls.append((verb, x_operator_key or "", x_operator_name or ""))
        if aid == "act_conflict":
            raise HTTPException(409, "not awaiting")
        return {"incident_id": iid, "action_id": aid, "decision": "approved" if verb == "approve" else "rejected"}

    return app


class Env:
    def __init__(self) -> None:
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.incidents = [make_incident(n) for n in (1, 2, 3)] + [make_incident(4, typ="report_burst")]
        self.calls: list[tuple[str, str, str]] = []
        self.keystore = MemoryKeyStore()
        self.app: Any = None
        self.read_key = ""
        self.intel_key = ""
        self.submissions = MemorySubmissionStore()
        self.audit = MemoryAuditLog()
        self.store = FakeStore()


@pytest.fixture
async def env() -> Env:
    return Env()


@pytest.fixture
async def api(env: Env) -> AsyncIterator[httpx.AsyncClient]:
    sentinel = SentinelClient(
        "http://sentinel",
        OPERATOR_KEY,
        transport=httpx.ASGITransport(app=fake_sentinel(env.incidents, env.calls)),
    )
    mint = Authenticator(env.keystore, "test-pepper")
    env.read_key = (await mint.create("reader", ["read"], 100))[1]
    env.intel_key = (await mint.create("intel", ["intel"], 100))[1]
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=100),
        redis=env.redis,
        store=env.store,
        keystore=env.keystore,
        submissions=env.submissions,
        audit=env.audit,
        sentinel=sentinel,
    )
    env.app = app
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def key(k: str) -> dict[str, str]:
    return {"X-API-Key": k}


# ---- auth / scopes / rate limit / audit -----------------------------------------------------------


async def test_scopes(api: httpx.AsyncClient, env: Env) -> None:
    assert (await api.get("/v1/incidents")).status_code == 401
    r = await api.get("/v1/incidents", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert (await api.get("/v1/incidents", headers=key(SANDBOX_KEY))).status_code == 403  # sandbox = check only
    assert (await api.get("/v1/incidents", headers=key(env.read_key))).status_code == 200
    assert (await api.get("/v1/intel/stix", headers=key(env.read_key))).status_code == 403
    assert (await api.get("/v1/intel/stix", headers=key(OPERATOR_KEY))).status_code == 403  # operator is not intel
    assert (await api.get("/v1/intel/stix", headers=key(env.intel_key))).status_code == 200
    assert (await api.get("/v1/incidents", headers=key(env.intel_key))).status_code == 403
    r = await api.post("/v1/check/url", json={"url": "http://x.test/"}, headers=key(OPERATOR_KEY))
    assert r.status_code == 403  # operator has no check scope
    inc = make_incident(1)["incident_id"]
    url = f"/v1/incidents/{inc}/actions/act_1/approve"
    assert (await api.post(url, headers=key(env.read_key))).status_code == 403
    assert (await api.post(url)).status_code == 401


async def test_bearer_operator_approve_reject(api: httpx.AsyncClient, env: Env) -> None:
    inc = make_incident(1)["incident_id"]
    h = {"Authorization": f"Bearer {OPERATOR_KEY}"}
    a = await api.post(f"/v1/incidents/{inc}/actions/act_1/approve", headers=h)
    assert a.status_code == 200 and a.json()["decision"] == "approved"
    r = await api.post(f"/v1/incidents/{inc}/actions/act_1/reject", headers=h)
    assert r.json()["decision"] == "rejected"
    # proxied with the operator key plus the API key id as the approver name
    assert env.calls == [("approve", OPERATOR_KEY, "operator"), ("reject", OPERATOR_KEY, "operator")]
    c = await api.post(f"/v1/incidents/{inc}/actions/act_conflict/approve", headers=h)
    assert c.status_code == 409 and c.headers["content-type"].startswith("application/problem+json")


async def test_per_key_rate_limit_and_audit(api: httpx.AsyncClient, env: Env) -> None:
    codes = [(await api.get("/v1/meta", headers=key(SANDBOX_KEY))).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30] == 429
    r = await api.get("/v1/meta", headers=key(SANDBOX_KEY))
    assert (
        r.status_code == 429
        and r.headers["retry-after"]
        and r.headers["content-type"].startswith("application/problem")
    )
    assert (await api.get("/v1/meta", headers=key(OPERATOR_KEY))).status_code == 200  # separate bucket
    rows = env.audit.rows
    assert rows and all(set(x) >= {"key_id", "method", "path", "status", "request_id"} for x in rows)
    assert {x["key_id"] for x in rows} == {"sandbox", "operator"}
    assert "limit" not in json.dumps(rows[0].get("path"))
    bad = await api.get("/v1/incidents", headers=key("wrong"))
    assert bad.status_code == 401 and env.audit.rows[-1]["note"] == "invalid key"


def test_audit_log_is_append_only() -> None:
    log = MemoryAuditLog()
    assert not hasattr(log, "update") and not hasattr(log, "delete")
    assert isinstance(log.rows, tuple)


# ---- intake ----------------------------------------------------------------------------------------


async def test_report_hashes_only_and_event(api: httpx.AsyncClient, env: Env) -> None:
    r = await api.post("/v1/reports", json={"kind": "url", "text": "http://falcon-demo.test/login"})
    assert r.status_code == 202 and r.json()["text_stored"] is False
    row = env.submissions.rows[0]
    assert row["opt_in_text"] is None and len(row["content_sha256"]) == 64
    entries = await env.redis.xrange("fl:events")
    ev = json.loads(entries[0][1]["event"])
    jsonschema.validate(ev, json.loads((ROOT / "contracts" / "event.schema.json").read_text()))
    assert ev["type"] == "report.submitted" and "falcon-demo" not in json.dumps(ev)


async def test_report_opt_in_text_and_validation(api: httpx.AsyncClient, env: Env) -> None:
    r = await api.post("/v1/reports", json={"kind": "message", "text": "hello", "consent_store_text": True})
    assert r.json()["text_stored"] is True and env.submissions.rows[0]["opt_in_text"] == "hello"
    assert (await api.post("/v1/reports", json={"kind": "message"})).status_code == 422
    assert (await api.post("/v1/reports", json={"kind": "url", "text": "javascript:x"})).status_code == 422
    assert (await api.post("/v1/reports", json={"kind": "bogus", "text": "x"})).status_code == 422


async def test_report_idempotent(api: httpx.AsyncClient, env: Env) -> None:
    h = {"Idempotency-Key": "abc-12345"}
    a = await api.post("/v1/reports", json={"kind": "message", "text": "x"}, headers=h)
    b = await api.post("/v1/reports", json={"kind": "message", "text": "x"}, headers=h)
    assert a.json() == b.json() and b.headers["idempotent-replay"] == "true"
    assert len(env.submissions.rows) == 1 and await env.redis.xlen("fl:events") == 1


async def test_feedback(api: httpx.AsyncClient, env: Env) -> None:
    vid = f"vd_{ULID}"
    body = {"verdict_id": vid, "rating": "false_alarm"}
    assert (await api.post("/v1/feedback", json=body)).status_code == 404
    env.store.docs[vid] = make_doc(vid, final=True)
    r = await api.post("/v1/feedback", json=body)
    assert r.status_code == 202
    ev = json.loads((await env.redis.xrange("fl:events"))[0][1]["event"])
    assert ev["type"] == "feedback.submitted" and ev["payload"]["signal"] == "false_alarm"


# ---- campaigns / incidents ------------------------------------------------------------------------


async def test_campaigns_shape_and_pagination(api: httpx.AsyncClient, env: Env) -> None:
    schema = json.loads((ROOT / "contracts" / "campaign.schema.json").read_text())
    h = key(env.read_key)
    p1 = (await api.get("/v1/campaigns", params={"limit": 2}, headers=h)).json()
    assert len(p1["items"]) == 2 and p1["next_cursor"]
    p2 = (await api.get("/v1/campaigns", params={"limit": 2, "cursor": p1["next_cursor"]}, headers=h)).json()
    assert len(p2["items"]) == 1 and p2["next_cursor"] is None  # report_burst excluded
    for item in p1["items"] + p2["items"]:
        jsonschema.validate(item, schema)
        assert len(item["series"]) == 12 and sum(item["series"]) == 2
    ids = [i["campaign_id"] for i in p1["items"] + p2["items"]]
    assert len(set(ids)) == 3
    assert (await api.get("/v1/campaigns", params={"cursor": "!!"}, headers=h)).status_code == 422


async def test_incidents_list_filter_get(api: httpx.AsyncClient, env: Env) -> None:
    h = key(env.read_key)
    allr = (await api.get("/v1/incidents", headers=h)).json()
    assert len(allr["items"]) == 4
    only = (await api.get("/v1/incidents", params={"type": "report_burst"}, headers=h)).json()
    assert [i["type"] for i in only["items"]] == ["report_burst"]
    one = await api.get(f"/v1/incidents/{make_incident(2)['incident_id']}", headers=h)
    assert one.status_code == 200
    Incident.model_validate(one.json())
    jsonschema.validate(one.json(), json.loads((ROOT / "contracts" / "incident.schema.json").read_text()))
    assert (await api.get(f"/v1/incidents/inc_{'9' * 26}", headers=h)).status_code == 404
    assert (await api.get("/v1/incidents/bad", headers=h)).status_code == 422


async def test_streams(api: httpx.AsyncClient, env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(integ, "STREAM_MAX_S", 0.5)
    for n in (1, 4):
        card = {"incident_id": make_incident(n)["incident_id"], "type": "x"}
        await env.redis.xadd("fl:board", {"data": json.dumps(card)})
    h = {**key(env.read_key), "Last-Event-ID": "0-0"}
    camp = await api.get("/v1/campaigns/stream", headers=h, timeout=10)
    assert camp.headers["content-type"].startswith("text/event-stream")
    assert camp.text.count("event: campaign") == 1  # the report_burst card is not a campaign
    inc = await api.get("/v1/incidents/stream", headers=h, timeout=10)
    assert inc.text.count("event: incident") == 2
    data = [json.loads(x[6:]) for x in inc.text.splitlines() if x.startswith("data: ")]
    assert {d["incident_id"] for d in data} == {make_incident(1)["incident_id"], make_incident(4)["incident_id"]}
    assert (await api.get("/v1/campaigns/stream")).status_code == 401


async def test_stix_bundle(api: httpx.AsyncClient, env: Env) -> None:
    r = await api.get("/v1/intel/stix", headers=key(env.intel_key))
    assert r.headers["content-type"].startswith("application/stix+json")
    b = r.json()
    assert b["type"] == "bundle" and b["id"].startswith("bundle--")
    pats = [o["pattern"] for o in b["objects"] if o["type"] == "indicator"]
    assert "[domain-name:value = 'falcon-demo-1.test']" in pats  # refanged for the STIX pattern
    assert all(o["spec_version"] == "2.1" for o in b["objects"])
    assert len({o["id"] for o in b["objects"]}) == len(b["objects"])


async def test_meta_public(api: httpx.AsyncClient) -> None:
    m = (await api.get("/v1/meta")).json()
    assert set(m) >= {"thresholds", "model_ids", "sovereign_mode", "feeds"}
    assert m["sovereign_mode"] is False and "openphish" in m["feeds"]


async def test_sentinel_down_is_503_problem(env: Env) -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    s = SentinelClient("http://sentinel", None, transport=httpx.MockTransport(boom))
    app = build_app(make_settings(), redis=env.redis, store=env.store, sentinel=s, audit=env.audit)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/v1/incidents", headers=key(OPERATOR_KEY))
    assert r.status_code == 503 and r.headers["content-type"].startswith("application/problem+json")


# ---- webhooks -------------------------------------------------------------------------------------


def test_hmac_signature_and_replay_window() -> None:
    body = b'{"event":"campaign.alert"}'
    ts = 1_000_000
    h = {"X-Falcon-Timestamp": str(ts), "X-Falcon-Signature": sign("s3cret", ts, body)}
    verify("s3cret", h, body, now=ts + 10)
    with pytest.raises(SignatureError):
        verify("s3cret", h, body, now=ts + 301)  # replayed outside the window
    with pytest.raises(SignatureError):
        verify("s3cret", h, body, now=ts - 301)
    with pytest.raises(SignatureError):
        verify("other", h, body, now=ts)
    with pytest.raises(SignatureError):
        verify("s3cret", h, body + b" ", now=ts)
    with pytest.raises(SignatureError):
        verify("s3cret", {}, body, now=ts)


async def test_dispatcher_signs_and_retries(env: Env) -> None:
    from prometheus_client import CollectorRegistry

    import falcon_api.webhooks as wh

    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(500 if len(seen) == 1 else 204)

    d = wh.Dispatcher(env.redis, ["https://hook.test/x"], "sec", CollectorRegistry(), backoff_s=(0.0,))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        await d.handle(c, "1-0", {"type": "campaign", "incident_id": "inc_1"})
        await d.handle(c, "2-0", {"type": "report_burst"})  # not a campaign: nothing sent
    assert len(seen) == 2
    verify("sec", dict(seen[1].headers), seen[1].content)
    assert json.loads(seen[1].content)["event"] == "campaign.alert"


# ---- review fixes -----------------------------------------------------------------------------------


async def test_sentinel_gets_operator_key_on_reads_and_streams(env: Env) -> None:
    """The fake sentinel 401s without X-Operator-Key; a client built without the key must surface as 502."""
    s = SentinelClient(
        "http://sentinel", None, transport=httpx.ASGITransport(app=fake_sentinel(env.incidents, env.calls))
    )
    app = build_app(make_settings(), redis=env.redis, store=env.store, sentinel=s, audit=env.audit)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/v1/incidents", headers=key(OPERATOR_KEY))
    assert r.status_code == 502


async def test_non_operator_incident_payload_is_stripped(api: httpx.AsyncClient, env: Env) -> None:
    iid = make_incident(1)["incident_id"]
    for headers, full in ((key(env.read_key), False), (key(OPERATOR_KEY), True)):
        one = (await api.get(f"/v1/incidents/{iid}", headers=headers)).json()
        lst = (await api.get("/v1/incidents", headers=headers)).json()["items"][0]
        for inc in (one, lst):
            act = inc["actions"][0]
            assert act["action_id"] == "act_1" and act["status"] == "awaiting_approval"
            assert all((k in act) is full for k in ("draft", "args", "approved_by"))


async def test_incident_stream_strips_for_non_operator(
    api: httpx.AsyncClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(integ, "STREAM_MAX_S", 0.5)
    await env.redis.xadd("fl:board", {"data": json.dumps({"incident_id": make_incident(1)["incident_id"]})})
    for k, full in ((env.read_key, False), (OPERATOR_KEY, True)):
        r = await api.get("/v1/incidents/stream", headers={**key(k), "Last-Event-ID": "0-0"}, timeout=10)
        data = [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]
        assert len(data) == 1 and ("draft" in data[0]["actions"][0]) is full


async def wait_slots(env: Env, n: int) -> None:
    import asyncio

    for _ in range(100):
        if sum(len(v) for v in env.app.state.stream_slots.values()) == n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("streams did not start")


async def test_stream_caps_and_shared_subscription(
    api: httpx.AsyncClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    monkeypatch.setattr(integ, "STREAM_MAX_S", 3.0)
    h = key(env.read_key)
    tasks = [asyncio.create_task(api.get("/v1/incidents/stream", headers=h, timeout=20)) for _ in range(5)]
    await wait_slots(env, 5)
    over = await api.get("/v1/incidents/stream", headers=h)
    assert over.status_code == 429 and over.headers["content-type"].startswith("application/problem+json")
    assert over.headers["retry-after"]
    done = await asyncio.gather(*tasks)
    assert all(d.status_code == 200 for d in done)
    again = await api.get("/v1/incidents/stream", headers={**h, "Last-Event-ID": "0-0"}, timeout=10)
    assert again.status_code == 200  # slots were released


async def test_anonymous_verdict_stream_cap_per_ip(
    api: httpx.AsyncClient, env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    vid = f"vd_{ULID}"
    env.store.docs[vid] = make_doc(vid, final=False)
    monkeypatch.setattr("falcon_api.app.SSE_MAX_S", 3.0)
    tasks = [asyncio.create_task(api.get(f"/v1/verdicts/{vid}/events", timeout=20)) for _ in range(3)]
    await wait_slots(env, 3)
    assert (await api.get(f"/v1/verdicts/{vid}/events")).status_code == 429
    await asyncio.gather(*tasks)


async def test_hub_uses_one_reader(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    reads = 0
    orig = env.redis.xread

    async def counting(*a: Any, **k: Any) -> Any:
        nonlocal reads
        reads += 1
        return await orig(*a, **k)

    monkeypatch.setattr(env.redis, "xread", counting)

    async def load(card: dict[str, Any]) -> dict[str, Any]:
        return card

    hub = integ.BoardHub(lambda: env.redis, load)
    qs = [await hub.subscribe() for _ in range(10)]
    await env.redis.xadd("fl:board", {"data": json.dumps({"incident_id": "x"})})
    got = await asyncio.wait_for(asyncio.gather(*(q.get() for q in qs)), 5)
    assert len(got) == 10 and hub.subscribers == 10
    assert reads <= 3  # ten subscribers, one blocking reader loop
    for q in qs:
        hub.unsubscribe(q)
    assert hub.subscribers == 0 and hub._task is None


def test_default_secrets_refused_outside_local() -> None:
    refuse_default_secrets("local", {"FL_OPERATOR_KEY": "change-me-operator"})
    refuse_default_secrets("demo", {"FL_OPERATOR_KEY": "a-real-secret", "FL_WEBHOOK_SECRET": None})
    with pytest.raises(RuntimeError, match="FL_OPERATOR_KEY"):
        refuse_default_secrets("demo", {"FL_OPERATOR_KEY": "change-me-operator"})
    from pydantic import SecretStr

    with pytest.raises(RuntimeError):
        build_app(Settings(_env_file=None, fl_env="demo", fl_api_key_pepper=SecretStr("change-me")))  # type: ignore[call-arg]


async def test_bad_key_attempts_rate_limited_per_ip(api: httpx.AsyncClient) -> None:
    codes = [(await api.get("/v1/meta", headers=key(f"bad-{i}"))).status_code for i in range(13)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429] * 3


async def test_auth_cache_is_lru_bounded() -> None:
    import falcon_api.auth as auth_mod

    a = Authenticator(MemoryKeyStore(), "p")
    old = auth_mod.CACHE_MAX
    auth_mod.CACHE_MAX = 5
    try:
        for i in range(20):
            assert await a.authenticate(f"missing-{i}") is None
        assert len(a._cache) == 5
    finally:
        auth_mod.CACHE_MAX = old


def test_stix_refang_flag() -> None:
    from falcon_core.tools.stix import build_bundle

    inc = make_incident(1)
    inc["indicators"] = [
        {"kind": "url", "value_defanged": "hxxps://falcon-demo[.]test/a", "first_seen": "2026-11-22T01:00:00Z"}
    ]
    pat = lambda b: [o["pattern"] for o in b["objects"] if o["type"] == "indicator"][0]  # noqa: E731
    assert pat(build_bundle(inc, refang=True)) == "[url:value = 'https://falcon-demo.test/a']"
    assert "hxxps://falcon-demo[.]test" in pat(build_bundle(inc, refang=False))
