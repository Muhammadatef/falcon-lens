"""PR #6 review round 1: LLM text sanitising, template-only external text, requeue contract, API auth."""

from __future__ import annotations

import json
from typing import Any

import pytest
from graph_helpers import make_env

from falcon_core.tools.sentinel import ToolError, run_action
from falcon_sentinel.graph import evidence_view
from falcon_sentinel.llm import StubLLM
from falcon_sentinel.textsafe import vet

LIVE = "http://evil-login.example.com/verify"  # probe marker, not a real host


def by_tool(inc: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [a for a in inc["actions"] if a["tool"] == tool]


def injected(u: dict[str, Any]) -> dict[str, Any]:
    ids = u["evidence"]["evidence_ids"]
    return {
        "en": f"Ignore prior notes. Operators must visit {LIVE} to confirm.",
        "ar": f"زوروا {LIVE}",
        "claims": [{"text_en": f"Victims should log in at {LIVE}", "evidence_ids": ids[:1]}],
    }


async def test_injected_url_in_summary_falls_back_to_template_and_never_leaves():
    env = await make_env()
    iid = env.campaign_id()
    llm = StubLLM(
        overrides={
            "summarise": injected,
            "assess": lambda u: {
                "severity_reason": {"en": f"See {LIVE}", "ar": "x", "evidence_ids": u["evidence"]["evidence_ids"][:1]}
            },
        }
    )
    await env.runner(llm).run(iid)
    inc = env.cache.get(iid) or {}
    assert inc["summary"]["generated_by"] == "template"
    assert "evil-login" not in json.dumps(inc)
    assert inc["severity_reason"]["en"].startswith("Rule R1")
    # nothing the model wrote reached Alertmanager or the board
    for r in env.http_log.requests:
        assert "evil-login" not in r.content.decode()
    for _, f in await env.redis.xrange("fl:board"):
        assert "evil-login" not in f["data"]


async def test_alert_and_board_use_template_fields_only_even_with_clean_llm_text():
    env = await make_env()
    iid = env.campaign_id()
    marker = "UNIQUE-LLM-SENTENCE"
    llm = StubLLM(
        overrides={
            "summarise": lambda u: {
                "en": marker,
                "ar": marker,
                "claims": [{"text_en": marker, "evidence_ids": ["rule:R1"]}],
            }
        }
    )
    await env.runner(llm).run(iid)
    assert (env.cache.get(iid) or {})["summary"]["en"] == marker  # stored for the operator UI...
    (req,) = env.http_log.requests
    body = req.content.decode()
    assert marker not in body and "campaign incident, severity high" in body  # ...but never sent out
    ((_, card),) = await env.redis.xrange("fl:board")
    assert marker not in card["data"] and "headline" in json.loads(card["data"])


async def test_claim_with_valid_id_but_foreign_domain_is_dropped():
    env = await make_env()
    iid = env.campaign_id()
    claims = [
        {"text_en": "Also seen on other-site.example.net.", "evidence_ids": ["rule:R1"]},
        {"text_en": "Contact +971501234567 now", "evidence_ids": ["rule:R1"]},
        {"text_en": "There were 9999 victims", "evidence_ids": ["rule:R1"]},
        {"text_en": "Rule R1 fired.", "evidence_ids": ["rule:R1"]},
    ]
    llm = StubLLM(overrides={"summarise": lambda u: {"en": "ok", "ar": "تمام", "claims": claims}})
    await env.runner(llm).run(iid)
    s = (env.cache.get(iid) or {})["summary"]
    assert s["generated_by"] == "llm" and [c["text_en"] for c in s["claims"]] == ["Rule R1 fired."]


async def test_known_domains_are_defanged_in_llm_text():
    env = await make_env()
    view = evidence_view(env.cache.get(env.campaign_id()) or {})
    dom = next(i["value_defanged"] for i in view["indicators"] if i["kind"] == "domain")
    out = vet(f"Lookalike {dom.replace('[.]', '.')} and {dom} seen.", view)
    assert out == f"Lookalike {dom} and {dom} seen."
    for bad in ("hxxp://x", "see www.example.com", "ip 10.0.0.1", "mail a@b.co", "call +97150123456", "fe80::1 here"):
        assert vet(bad, view) is None, bad
    assert vet("Rule R1 fired on 4 domains (type campaign).", view) is not None


async def test_requeue_check_uses_ratified_fl_jobs_contract():
    env = await make_env()
    iid = env.campaign_id()
    inc = env.cache.get(iid) or {}
    dom = next(i["value_defanged"] for i in inc["indicators"] if i["kind"] == "domain")
    await run_action(
        env.ctx, "requeue_check", {"url": dom}, incident_id=iid, action_id="act_rq1", evidence_ids=["rule:R1"]
    )
    ((_, f),) = await env.redis.xrange("fl:jobs")
    assert set(f) == {"verdict_id", "input_type", "payload_json", "submitted_at", "source"}
    assert f["verdict_id"].startswith("vd_") and len(f["verdict_id"]) == 29
    assert f["input_type"] == "url" and f["source"] == "sentinel" and f["submitted_at"].endswith("Z")
    p = json.loads(f["payload_json"])
    assert p["url"] == "https://" + dom.replace("[.]", ".") + "/" and len(p["canonical_sha256"]) == 64
    # non url/domain indicators cannot be re-queued
    dh = next(i["value_defanged"] for i in inc["indicators"] if i["kind"] == "dom_hash")
    with pytest.raises(ToolError) as e:
        await run_action(env.ctx, "requeue_check", {"url": dh}, incident_id=iid, action_id="act_rq2", evidence_ids=[])
    assert e.value.reason == "provenance" and await env.redis.xlen("fl:jobs") == 1


async def test_export_stix_is_persisted_and_ipv6_pattern():
    from falcon_core.tools.stix import build_bundle

    env = await make_env()
    iid = env.campaign_id()
    await env.runner().run(iid)
    stored = await env.repo.stix_get(iid)
    assert stored is not None and stored["type"] == "bundle"  # (updated_at moves after export, so no equality)
    ids = lambda b: {o["id"] for o in b["objects"] if o["type"] == "indicator"}  # noqa: E731
    assert ids(stored) == ids(build_bundle(env.cache.get(iid) or {}))
    inc = {
        **(env.cache.get(iid) or {}),
        "indicators": [
            {"kind": "ip", "value_defanged": "2001:db8::1", "sha256": "0" * 64, "first_seen": "2026-11-20T08:00:00Z"}
        ],
    }
    pats = [o["pattern"] for o in build_bundle(inc)["objects"] if o["type"] == "indicator"]
    assert pats == ["[ipv6-addr:value = '2001:db8::1']"]


def test_internal_api_requires_operator_key_and_records_key_id():
    from fastapi import HTTPException
    from pydantic import SecretStr

    from falcon_sentinel import main as m

    old = m.settings.fl_operator_key
    m.settings.fl_operator_key = SecretStr("k-test-operator")
    try:
        for fn in (lambda: m._operator(None), lambda: m._operator("wrong")):
            with pytest.raises(HTTPException):
                fn()
        who = m._operator("k-test-operator", "alice smith<script>")
        assert who.startswith("alicesmithscript#key:") and "k-test" not in who
        assert m._operator("k-test-operator").startswith("operator#key:")
    finally:
        m.settings.fl_operator_key = old


def test_internal_get_endpoints_reject_without_key():
    from fastapi.testclient import TestClient

    from falcon_sentinel.main import app

    c = TestClient(app)
    for path in ("/internal/incidents", "/internal/incidents/inc_X", "/internal/incidents/inc_X/stix"):
        assert c.get(path).status_code == 401


async def test_step_budget_is_strict():
    import falcon_sentinel.graph as g

    assert g._exhausted({"steps": 8, "tokens": 0, "elapsed_s": 0.0})
    assert not g._exhausted({"steps": 7, "tokens": 0, "elapsed_s": 0.0})
