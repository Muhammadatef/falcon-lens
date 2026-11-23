"""The sandbox's flat /render shape (PR #28 ``compat.to_flat``) drives T2 evidence and H4."""

from __future__ import annotations

from cascade_helpers import age_signal, assert_valid, make_cascade, offline_signals, rules, run

from falcon_core.cascade import SandboxFeatures, StubSandboxClient
from falcon_core.cascade.testing import DEMO_BENIGN_URL, DEMO_LOOKALIKE_URL


async def test_sandbox_exfil_targets_trigger_h4_on_phish_fixture() -> None:
    flat = {
        "verdict_id": "vd_x",
        "final_url": DEMO_LOOKALIKE_URL,
        "title": "Falcon Demo Bank | Online Banking Login",
        "forms": [{"fields": ["password", "card number"], "action_origin": None}],
        "post_targets": ["https://falcon-bot-relay.test"],
        "exfil_targets": [{"origin": "https://falcon-bot-relay.test", "category": "messaging_bot_api"}],
        "hotlinked_origins": [],
        "visible_text": "TEST FIXTURE, not a real site.",
        "cloaking": {"detected": False, "diff": False, "simhash_distance": 2, "reasons": []},
        "profiles": {"mobile_ar": {}},
        "elapsed_ms": 900,
        "error": None,
    }
    cascade, _ = make_cascade(StubSandboxClient(default=SandboxFeatures.model_validate(flat)))
    final = (await run(cascade, DEMO_LOOKALIKE_URL)).docs[-1]
    assert_valid(final)
    assert final["verdict"] == "dangerous"
    assert {"H1", "H4"} <= rules(final)
    post = next(e for e in final["evidence"] if e["signal"] == "page.cross_origin_post")
    assert post["observed"]["target_kind"] == "messaging_bot" and post["observed"]["bot"] is True


async def test_target_refusal_on_established_clean_domain_is_not_degraded() -> None:
    feats = SandboxFeatures.model_validate({"error": "tls_error", "final_url": None})
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    assert not final["degraded"] and final["verdict"] == "no_warning_signs" and final["tier_reached"] == "T2"
    ev = next(e for e in final["evidence"] if e["signal"] == "sandbox.not_rendered")
    assert ev["weight"] == 0 and "could not open the page" in ev["display"]["en"]


async def test_sandbox_failure_degrades_without_trust_with_risk_or_on_internal_error() -> None:
    feats = SandboxFeatures.model_validate({"error": "x", "final_url": None})  # unknown code: fail closed
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and "sandbox_unavailable:x" in final["degraded_reasons"]
    soft = SandboxFeatures.model_validate({"error": "timeout", "final_url": None})
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=soft), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_LOOKALIKE_URL)).docs[-1]  # url.* risk evidence present
    assert final["degraded"]
    cascade, _ = make_cascade(
        force_t2=True,
        sandbox=StubSandboxClient(error="unreachable:ConnectError"),
        signals=offline_signals(age_signal(9000)),
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and final["verdict"] != "no_warning_signs"
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(error="timeout")
    )  # no domain-age evidence: no page-independent trust
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and final["verdict"] != "no_warning_signs"


async def test_policy_block_codes_always_degrade() -> None:
    for code in ("blocked_by_policy", "egress_blocked", "too_many_redirects", "size_cap"):
        feats = SandboxFeatures.model_validate({"error": code, "final_url": None})
        cascade, _ = make_cascade(
            force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
        )
        final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
        assert final["degraded"] and f"sandbox_unavailable:{code}" in final["degraded_reasons"], code


async def test_truncated_page_is_evidence_with_weight_zero_not_an_error() -> None:
    """A page the sandbox could only read in part (cut at the size cap, or half-loaded) is judged on what
    was read: the informational ``page.truncated`` evidence carries weight 0 and the check is not degraded."""
    feats = SandboxFeatures.model_validate(
        {
            "final_url": DEMO_BENIGN_URL,
            "title": "Garden club events",
            "visible_text": "TEST FIXTURE, not a real site.",
            "truncated": True,
            "partial": True,
            "error": None,
        }
    )
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    ev = next(e for e in final["evidence"] if e["signal"] == "page.truncated")
    assert ev["weight"] == 0 and ev["observed"] == {"truncated": True, "partial": True} and ev["error"] is None
    assert not final.get("degraded")


def _partial(**kw: object) -> SandboxFeatures:
    return SandboxFeatures.model_validate(
        {"final_url": DEMO_BENIGN_URL, "title": "Garden club events", "partial": True, "error": None, **kw}
    )


async def test_partial_read_on_unknown_domain_is_degraded_not_cleared() -> None:
    """Fail closed: a half-read page is held to the same rule as an unopened one (no trust evidence -> degraded)."""
    cascade, _ = make_cascade(force_t2=True, sandbox=StubSandboxClient(default=_partial()), signals=offline_signals())
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert_valid(final)
    assert final["degraded"] and "partial_render" in final["degraded_reasons"]
    assert final["verdict"] != "no_warning_signs"


async def test_partial_read_on_established_domain_without_risk_may_clear() -> None:
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=_partial()), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert not final["degraded"], final["degraded_reasons"]
    assert final["verdict"] == "no_warning_signs"
    assert any(e["signal"] == "page.truncated" for e in final["evidence"])


async def test_partial_read_with_page_risk_is_degraded_even_on_established_domain() -> None:
    feats = _partial(forms=[{"fields": ["password"], "action_origin": None}])
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and "partial_render" in final["degraded_reasons"]


async def test_inconclusive_cloaking_comparison_is_visible_evidence_weight_zero() -> None:
    feats = _partial(cloaking={"detected": False, "diff": False, "inconclusive": True, "reasons": []})
    cascade, _ = make_cascade(
        force_t2=True, sandbox=StubSandboxClient(default=feats), signals=offline_signals(age_signal(9000))
    )
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    ev = next(e for e in final["evidence"] if e["signal"] == "page.cloaking_inconclusive")
    assert ev["weight"] == 0
