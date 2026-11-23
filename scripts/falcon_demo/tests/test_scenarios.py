"""`make demo` scenario runner: pass/fail/skipped accounting, exit codes, replay pacing. No network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from falcon_demo import scenarios
from falcon_demo.common import SANDBOX_KEY_PER_MIN, SERVICE_KEY_PER_MIN, paced_rate, pick_key


def _verdict(verdict: str, rules: tuple[str, ...] = (), signals: tuple[str, ...] = (), **extra: Any) -> dict[str, Any]:
    ev = [{"signal": s, "hard_rule": None} for s in signals] + [{"signal": "x", "hard_rule": r} for r in rules]
    return {
        "verdict": verdict,
        "verdict_id": "vd_TEST",
        "final": True,
        "evidence": ev,
        "actions": {"caution": {"en": "stay careful"}},
        **extra,
    }


def _runner(answers: dict[str, dict[str, Any]]) -> scenarios.Runner:
    def handler(req: httpx.Request) -> httpx.Response:
        hint = req.url.path + req.content.decode(errors="ignore")
        for needle, doc in answers.items():
            if needle in hint:
                return httpx.Response(200, json=doc)
        return httpx.Response(500)

    c = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://localhost:1")
    return scenarios.Runner({"FL_SANDBOX_API_KEY": "k"}, client=c)


# Order matters: the first needle found in "path + body" answers, so specific ones come first.
GOOD = {
    "injection.test": _verdict("suspicious", signals=("injection.instruction_like_text",)),
    "/v1/check/message": _verdict("dangerous", ("H5",)),
    "/v1/check/email": _verdict("dangerous", signals=("email.display_name_impersonation",)),
    "secure.test": _verdict("dangerous", ("H1",)),
    "falcon-demo-bank.test": _verdict("no_warning_signs", ("H3",)),
}


def test_all_pass_but_feed_skipped_without_private_mirror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scenarios, "FEED_DIR", tmp_path / "absent")
    rows = scenarios.run_all(_runner(GOOD), sentinel=False)
    assert rows[0].status == scenarios.SKIPPED and "mirror" in rows[0].note
    assert [r.status for r in rows[1:]] == [scenarios.PASS] * 5
    assert scenarios.exit_code(rows) == 0
    out = scenarios.render(rows)
    assert "1 not run" in out and "5 passed" in out and "vd_TEST" in out


def test_a_wrong_verdict_fails_and_exit_is_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scenarios, "FEED_DIR", tmp_path / "absent")
    bad = {**GOOD, "injection.test": _verdict("suspicious", degraded=True, degraded_reasons=["not_rendered"])}
    rows = scenarios.run_all(_runner(bad), sentinel=False)
    s6 = next(r for r in rows if r.name.startswith("6"))
    assert s6.status == scenarios.FAIL and "not rendered" in s6.note
    assert scenarios.exit_code(rows) == 1


def test_http_error_is_a_fail_not_a_crash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scenarios, "FEED_DIR", tmp_path / "absent")
    rows = scenarios.run_all(_runner({}), sentinel=False)
    assert all(r.status in (scenarios.FAIL, scenarios.SKIPPED) for r in rows)
    assert scenarios.exit_code(rows) == 1


def test_sentinel_scene_skipped_when_unhealthy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(scenarios, "FEED_DIR", tmp_path / "absent")
    rows = scenarios.run_all(_runner(GOOD), healthy=lambda: False)
    assert rows[-1].name == "S Sentinel scene" and rows[-1].status == scenarios.SKIPPED
    assert scenarios.exit_code(rows) == 0


def test_scenario_inputs_are_fixture_only() -> None:
    blob = scenarios.SMS_TEXT + scenarios.EML
    urls = [w.strip('"<>') for w in blob.replace('"', " ").split() if w.startswith("http")]
    assert urls and all(".test/" in u or u.endswith(".test") for u in urls)


def test_replay_pacing_keeps_below_the_key_limit() -> None:
    assert pick_key({"FL_MCP_SERVICE_KEY": "m", "FL_SANDBOX_API_KEY": "s"}) == ("m", SERVICE_KEY_PER_MIN)
    assert pick_key({"FL_SANDBOX_API_KEY": "s"}) == ("s", SANDBOX_KEY_PER_MIN)
    assert paced_rate(2.0, SERVICE_KEY_PER_MIN) * 60 <= SERVICE_KEY_PER_MIN * 0.8 + 1e-9
    assert paced_rate(0.2, SERVICE_KEY_PER_MIN) == 0.2
