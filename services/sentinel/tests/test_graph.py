from __future__ import annotations

import json
from typing import Any

import pytest
from graph_helpers import make_env
from jsonschema import Draft202012Validator
from sentinel_core.events import INCIDENT_SCHEMA_PATH, find_raw_text

from falcon_core.tools.sentinel import ToolError, run_action
from falcon_sentinel.graph import ApprovalError, evidence_view
from falcon_sentinel.llm import LLMOutputError, StubLLM


class Crash(Exception):  # not in the retry policy: simulates a process dying mid-run
    pass


def by_tool(inc: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [a for a in inc["actions"] if a["tool"] == tool]


async def test_planted_campaign_end_to_end_with_stub_llm():
    env = await make_env()
    iid = env.campaign_id()
    assert len([i for i in env.cache.all() if i["type"] == "campaign"]) == 1
    llm = StubLLM()
    runner = env.runner(llm)
    state = await runner.run(iid)
    inc = env.cache.get(iid)
    assert inc is not None
    Draft202012Validator(json.loads(INCIDENT_SCHEMA_PATH.read_text())).validate(inc)
    # bilingual summary, every claim cites evidence ids that exist in the evidence catalog
    ok_ids = set(evidence_view(inc)["evidence_ids"])
    s = inc["summary"]
    assert s["generated_by"] == "llm" and s["ar"] and s["en"] and s["claims"]
    assert all(c["evidence_ids"] and set(c["evidence_ids"]) <= ok_ids for c in s["claims"])
    assert inc["severity_reason"]["ar"] and inc["severity_reason"]["evidence_ids"]
    # exactly one block executed, with TTL in Redis and blocked_until on the indicator
    (blk,) = by_tool(inc, "block_indicator")
    assert blk["status"] == "executed"
    keys = [k async for k in env.redis.scan_iter("fl:block:*")]
    assert len(keys) == 1 and 0 < await env.redis.ttl(keys[0]) <= 72 * 3600
    assert sum(1 for i in inc["indicators"] if i["blocked_until"]) == 1
    # takedown waits for a human; nothing external was sent
    (td,) = by_tool(inc, "draft_takedown")
    assert td["status"] == "awaiting_approval" and td["draft"]["body_ar"] and td["draft"]["body_en"]
    assert inc["status"] == "awaiting_approval"
    assert state["__interrupt__"]
    assert [r.url.path for r in env.http_log.requests] == ["/api/v2/alerts"]  # only the internal Alertmanager
    assert await env.redis.xlen("fl:board") == 1
    assert by_tool(inc, "export_stix")[0]["status"] == "executed"
    assert by_tool(inc, "raise_alert")[0]["status"] == "executed"
    # audit trail
    audit = await env.repo.audit_list(iid)
    assert {
        "block_indicator",
        "draft_takedown",
        "raise_alert",
        "export_stix",
        "upsert_incident",
    } <= {a["tool"] for a in audit}
    assert all(a["evidence_ids"] is not None for a in audit)
    assert [c["task"] for c in llm.calls] == ["assess", "summarise", "propose"]

    # approve resumes the graph
    await runner.approve(iid, td["action_id"], "op_alice")
    inc = env.cache.get(iid)
    assert inc is not None
    (td,) = by_tool(inc, "draft_takedown")
    assert td["status"] == "approved" and td["approved_by"] == "op_alice"
    assert inc["status"] == "mitigated"
    assert {"decision": "approve", "sent": False} in [a["result"] for a in await env.repo.audit_list(iid)]
    assert [r.url.path for r in env.http_log.requests] == ["/api/v2/alerts"]  # still nothing sent externally
    with pytest.raises(ApprovalError):
        await runner.approve(iid, td["action_id"], "op_alice")  # nothing pending any more


async def test_reject_keeps_draft_unsent():
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner()
    await runner.run(iid)
    (td,) = by_tool(env.cache.get(iid) or {}, "draft_takedown")
    await runner.reject(iid, td["action_id"], "op_bob")
    (td,) = by_tool(env.cache.get(iid) or {}, "draft_takedown")
    assert td["status"] == "rejected" and td["approved_by"] is None


async def test_approval_needs_operator_and_pending_action():
    env = await make_env()
    iid = env.campaign_id()
    runner = env.runner()
    await runner.run(iid)
    with pytest.raises(ApprovalError):
        await runner.approve(iid, "act_nope", "op")
    (td,) = by_tool(env.cache.get(iid) or {}, "draft_takedown")
    with pytest.raises(ApprovalError):
        await runner.approve(iid, td["action_id"], "  ")


async def test_verifier_drops_uncited_claims_and_falls_back_to_template():
    env = await make_env()
    iid = env.campaign_id()
    bad = StubLLM(
        overrides={
            "summarise": lambda u: {
                "en": "x",
                "ar": "y",
                "claims": [
                    {"text_en": "uncited", "evidence_ids": []},
                    {"text_en": "bogus", "evidence_ids": ["evt_NOPE"]},
                ],
            }
        }
    )
    await env.runner(bad).run(iid)
    s = (env.cache.get(iid) or {})["summary"]
    assert s["generated_by"] == "template" and s["model_route"] == "none" and s["ar"] and s["en"]
    assert all(c["evidence_ids"] for c in s["claims"])

    env2 = await make_env()
    iid2 = env2.campaign_id()
    mixed = StubLLM(
        overrides={
            "summarise": lambda u: {
                "en": "x",
                "ar": "y",
                "claims": [
                    {"text_en": "uncited", "evidence_ids": []},
                    {"text_en": "ok", "evidence_ids": ["rule:R1", "evt_NOPE"]},
                ],
            }
        }
    )
    await env2.runner(mixed).run(iid2)
    s2 = (env2.cache.get(iid2) or {})["summary"]
    assert s2["generated_by"] == "llm" and s2["claims"] == [{"text_en": "ok", "evidence_ids": ["rule:R1"]}]


async def test_json_repair_retry_then_success_and_double_failure_degrades():
    env = await make_env()
    iid = env.campaign_id()
    n = {"c": 0}

    def flaky(u: dict[str, Any]) -> dict[str, Any]:
        n["c"] += 1
        return (
            {"nonsense": True}
            if n["c"] == 1
            else {"severity_reason": {"en": "e", "ar": "ع", "evidence_ids": ["rule:R1"]}}
        )

    llm = StubLLM(overrides={"assess": flaky})
    await env.runner(llm).run(iid)
    assert [c["repair"] for c in llm.calls if c["task"] == "assess"] == [False, True]
    assert (env.cache.get(iid) or {})["severity_reason"]["en"] == "e"

    env2 = await make_env()
    iid2 = env2.campaign_id()
    always_bad = StubLLM(overrides={"assess": lambda u: {"nope": 1}, "propose": lambda u: {"actions": "x"}})
    st = await env2.runner(always_bad).run(iid2)
    inc2 = env2.cache.get(iid2) or {}
    assert inc2["severity_reason"]["en"].startswith("Rule R1")  # template fallback
    assert {"assess", "propose"} <= set(st["degraded"])
    assert not by_tool(inc2, "block_indicator") and by_tool(inc2, "export_stix")  # deterministic internals still run


async def test_end_message_token_is_stripped():
    from falcon_sentinel.llm import clean_text

    assert json.loads(clean_text('```json\n{"a": 1}<|end_message|>\n```')) == {"a": 1}
    assert clean_text('{"a":1}<|end_message|>') == '{"a":1}'


async def test_proposals_obey_provenance_allowlist_and_citations():
    env = await make_env()
    iid = env.campaign_id()
    inc = env.cache.get(iid) or {}
    dom = next(i["value_defanged"] for i in inc["indicators"] if i["kind"] == "domain")
    evil = [
        {
            "tool": "block_indicator",
            "args": {"indicator": "not-in-incident[.]test", "ttl_hours": 24},
            "why_evidence_ids": ["rule:R1"],
        },
        {
            "tool": "block_indicator",
            "args": {"indicator": dom, "ttl_hours": 9999},
            "why_evidence_ids": ["rule:R1"],
        },
        {
            "tool": "block_indicator",
            "args": {"indicator": dom, "ttl_hours": 24},
            "why_evidence_ids": [],
        },
        {
            "tool": "upsert_incident",
            "args": {"incident_id": iid, "patch": {"severity": "low"}},
            "why_evidence_ids": ["rule:R1"],
        },
        {
            "tool": "draft_takedown",
            "args": {"incident_id": "inc_OTHER", "recipient_kind": "host"},
            "why_evidence_ids": ["rule:R1"],
        },
        {
            "tool": "block_indicator",
            "args": {"indicator": dom, "ttl_hours": 24},
            "why_evidence_ids": ["rule:R1"],
        },
    ]
    st = await env.runner(StubLLM(overrides={"propose": lambda u: {"actions": evil}})).run(iid)
    assert [r["reason"] for r in st["rejected"]] == [
        "provenance",
        "bad_args",
        "uncited",
        "not_allowed",
        "provenance",
    ]
    final = env.cache.get(iid) or {}
    assert len(by_tool(final, "block_indicator")) == 1 and final["severity"] == "high"


async def test_budget_exhaustion_skips_llm():
    env = await make_env()
    iid = env.campaign_id()
    llm = StubLLM()
    runner = env.runner(llm)
    import falcon_sentinel.graph as g

    old = g.MAX_TOKENS
    g.MAX_TOKENS = 1  # first LLM call spends >1 token, the rest must degrade
    try:
        st = await runner.run(iid)
    finally:
        g.MAX_TOKENS = old
    assert len(llm.calls) == 1 and {"summarise", "propose"} <= set(st["degraded"])
    assert (env.cache.get(iid) or {})["summary"]["generated_by"] == "template"
    assert st["budget"]["steps"] <= 8


async def test_agent_sees_structured_evidence_only():
    env = await make_env()
    for inc in env.cache.all():
        assert find_raw_text(evidence_view(inc)) is None
    llm = StubLLM()
    await env.runner(llm).run(env.campaign_id())
    assert "http" not in json.dumps(evidence_view(env.cache.get(env.campaign_id()) or {}))


async def test_restart_mid_run_resumes_from_checkpoint():
    from langgraph.checkpoint.memory import InMemorySaver

    env = await make_env()
    iid = env.campaign_id()
    saver = InMemorySaver()  # stands in for the Postgres checkpointer that survives the process
    crash = StubLLM(overrides={"propose": lambda u: Crash("process died")})
    with pytest.raises(Crash):
        await env.runner(crash, saver).run(iid)
    assert (env.cache.get(iid) or {})["status"] == "triaging"
    assert [c["task"] for c in crash.calls] == ["assess", "summarise", "propose"]
    # "restart": brand new runner/graph/LLM over the same checkpoint store
    fresh = StubLLM()
    runner2 = env.runner(fresh, saver)
    assert await runner2.resume_unfinished() == [iid]
    assert [c["task"] for c in fresh.calls] == ["propose"]  # assess and summarise were NOT redone
    assert (env.cache.get(iid) or {})["status"] == "awaiting_approval"
    # and a second restart while paused for approval does not re-run anything, approval still works
    runner3 = env.runner(StubLLM(), saver)
    assert await runner3.pending_approvals(iid)
    (td,) = by_tool(env.cache.get(iid) or {}, "draft_takedown")
    await runner3.approve(iid, td["action_id"], "op")
    assert (env.cache.get(iid) or {})["status"] == "mitigated"


async def test_unblock_reverts_block_and_counts():
    from falcon_core.tools.sentinel import unblock
    from falcon_sentinel.metrics import BLOCKS_REVERTED, SentinelMetrics

    env = await make_env()
    iid = env.campaign_id()
    await env.runner().run(iid)
    (blk,) = by_tool(env.cache.get(iid) or {}, "block_indicator")
    env.ctx.metrics = SentinelMetrics()
    before = BLOCKS_REVERTED._value.get()  # noqa: SLF001
    await unblock(env.ctx, blk["action_id"], "op_carol")
    assert [k async for k in env.redis.scan_iter("fl:block:*")] == []
    assert BLOCKS_REVERTED._value.get() == before + 1  # noqa: SLF001
    inc = env.cache.get(iid) or {}
    assert by_tool(inc, "block_indicator")[0]["status"] == "reverted" and not any(
        i["blocked_until"] for i in inc["indicators"]
    )
    assert (await env.repo.audit_list(iid))[-1]["tool"] == "unblock_indicator"
    assert await unblock(env.ctx, blk["action_id"], "op") == {"already_reverted": True}
    with pytest.raises(ToolError):
        await unblock(env.ctx, "act_missing", "op")


async def test_requeue_and_tool_arg_validation():
    env = await make_env()
    iid = env.campaign_id()
    dom = next(i["value_defanged"] for i in (env.cache.get(iid) or {})["indicators"] if i["kind"] == "domain")
    r = await run_action(
        env.ctx,
        "requeue_check",
        {"url": dom},
        incident_id=iid,
        action_id="act_t1",
        evidence_ids=["rule:R1"],
    )
    assert r.status == "executed" and await env.redis.xlen("fl:jobs") == 1
    with pytest.raises(ToolError) as e:
        await run_action(
            env.ctx,
            "block_indicator",
            {"indicator": dom, "ttl_hours": 0},
            incident_id=iid,
            action_id="act_t2",
            evidence_ids=[],
        )
    assert e.value.reason == "bad_args"
    with pytest.raises(ToolError):
        await run_action(
            env.ctx,
            "requeue_check",
            {"url": "evil[.]test"},
            incident_id=iid,
            action_id="act_t3",
            evidence_ids=[],
        )
    with pytest.raises(ToolError):
        await run_action(env.ctx, "send_email", {}, incident_id=iid, action_id="act_t4", evidence_ids=[])


async def test_alertmanager_failure_is_recorded_not_fatal():
    import httpx

    env = await make_env()
    env.ctx.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    iid = env.campaign_id()
    await env.runner().run(iid)
    inc = env.cache.get(iid) or {}
    assert (
        by_tool(inc, "raise_alert")[0]["status"] == "failed"
        and by_tool(inc, "block_indicator")[0]["status"] == "executed"
    )


async def test_stix_bundle_shape():
    from falcon_core.tools.stix import build_bundle

    env = await make_env()
    b = build_bundle(env.cache.get(env.campaign_id()) or {})
    assert b["type"] == "bundle" and b["id"].startswith("bundle--") and "spec_version" not in b
    kinds = {o["type"] for o in b["objects"]}
    assert kinds == {"identity", "indicator", "grouping"}
    for o in b["objects"]:
        assert o["spec_version"] == "2.1" and o["id"].startswith(o["type"] + "--") and o["created"].endswith("Z")
        if o["type"] == "indicator":
            assert o["pattern_type"] == "stix" and o["pattern"].startswith("[domain-name:value = '") and o["valid_from"]
        if o["type"] == "grouping":
            assert o["context"] and o["object_refs"]
    assert build_bundle(env.cache.get(env.campaign_id()) or {}) == b  # deterministic


def test_llm_output_error_type():
    assert issubclass(LLMOutputError, Exception)
