"""The sandbox's flat /render shape (PR #28 ``compat.to_flat``) drives T2 evidence and H4."""

from __future__ import annotations

from cascade_helpers import assert_valid, make_cascade, rules, run

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


async def test_sandbox_render_error_degrades() -> None:
    feats = SandboxFeatures.model_validate({"error": "net::ERR_NAME_NOT_RESOLVED", "final_url": None})
    cascade, _ = make_cascade(StubSandboxClient(default=feats))
    final = (await run(cascade, DEMO_BENIGN_URL)).docs[-1]
    assert final["degraded"] and "sandbox_unavailable:render_failed" in final["degraded_reasons"]
