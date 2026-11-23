"""Recorded answers from the local model (inkling-2-mini-chat) for the planted fixture campaign.

The two recorded files were rejected by the verifier before the fix although they are faithful: the model wrote
event type names ("domain.observed") that look like hosts, and glued the Arabic conjunction "و" onto a defanged
host. The bad case is synthetic (a recorded answer with an invented domain and an invented number); the
verifier must keep rejecting it. Fixture hosts are the invented Falcon Demo Bank *.test names only.
"""

from __future__ import annotations

from pathlib import Path

from graph_helpers import make_env

from falcon_core.llm import LLMRouter, RouterConfig
from falcon_core.llm.testing import ScriptedProvider
from falcon_sentinel.llm import RouterLLM

FIX = Path(__file__).parent / "fixtures"


def scripted(assess: str, summarise: str) -> RouterLLM:
    def reply(req) -> str:  # type: ignore[no-untyped-def]
        ctx = req.turns[-1].content
        if '"task": "assess"' in ctx:
            return assess
        if '"task": "summarise"' in ctx:
            return summarise
        return '{"actions": []}'

    local = ScriptedProvider("local", [reply])
    return RouterLLM(LLMRouter(RouterConfig(), local=local))


async def test_recorded_good_responses_are_accepted() -> None:
    env = await make_env()
    iid = env.campaign_id()
    llm = scripted(
        (FIX / "recorded_assess_event_type_names.txt").read_text(),
        (FIX / "recorded_summarise_arabic_clitic.txt").read_text(),
    )
    await env.runner(llm).run(iid)
    inc = env.cache.get(iid)
    assert inc is not None
    assert inc["summary"]["generated_by"] == "llm" and inc["summary"]["model_route"] == "local"
    assert "phishing-style infrastructure" in inc["severity_reason"]["en"]  # the model text, not the template
    assert inc["summary"]["claims"] and all(c["evidence_ids"] for c in inc["summary"]["claims"])


async def test_recorded_bad_response_stays_rejected() -> None:
    env = await make_env()
    iid = env.campaign_id()
    good = (FIX / "recorded_summarise_arabic_clitic.txt").read_text()
    bad = good.replace("falcondem0bank[.]test", "evil-bank-login[.]example", 1).replace("AS64500", "AS99999")
    llm = scripted((FIX / "recorded_assess_event_type_names.txt").read_text(), bad)
    await env.runner(llm).run(iid)
    inc = env.cache.get(iid)
    assert inc is not None and inc["summary"]["generated_by"] == "template"
