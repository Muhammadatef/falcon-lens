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


# ---- the verifier stays narrow ------------------------------------------------------------------


async def _view() -> dict:  # type: ignore[type-arg]
    from falcon_sentinel.graph import evidence_view

    env = await make_env()
    inc = env.cache.get(env.campaign_id())
    assert inc is not None
    return evidence_view(inc)


async def test_vet_event_types_come_from_the_contract_and_the_timeline() -> None:
    import json

    from sentinel_core.events import EVENT_SCHEMA_PATH

    from falcon_sentinel.textsafe import contract_event_types, vet

    view = await _view()
    assert contract_event_types() == frozenset(json.loads(EVENT_SCHEMA_PATH.read_text())["properties"]["type"]["enum"])
    assert vet("seen domain.observed then verdict.created", view) is not None
    # host-like but not a contract event type, even though it is shaped like one
    assert vet("seen domain.compromised", view) is None
    assert vet("see login.example", view) is None
    # a contract event type that this incident's timeline never shows is not vocabulary here
    assert vet("then incident.opened", view) is None


async def test_vet_arabic_clitic_only_passes_for_known_indicator_hosts() -> None:
    from falcon_sentinel.textsafe import vet

    view = await _view()
    assert vet("تشترك وfalcon-demo-bank-verify[.]test", view) is not None
    assert vet("تشترك وevil-bank-login[.]example", view) is None
    assert vet("تشترك وfalcon-demo-bank-verify[.]example", view) is None  # known name, other TLD


async def test_vet_rejects_urls_and_hosts_not_in_the_incident() -> None:
    from falcon_sentinel.textsafe import vet

    view = await _view()
    for bad in (
        "open hxxps://falcon-demo-bank-login[.]test/login",
        "open https://falcon-demo-bank-login.test/",
        "visit www.example.org",
        "another host other-demo-bank[.]test",
        "mail ops@falcon-demo-bank-login.test",
        "ip 203.0.113.9",
    ):
        assert vet(bad, view) is None, bad
