"""Review fixes for PR 21: reserved-domain allowlist (B2) and compose-derived reset names (B1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from falcon_demo import corpus, ops, seed


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def check_url(self, url: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        self.calls.append(url)
        return {"verdict_id": "vd_1"}

    def check_message(self, text: str, idem: str | None = None, wait: float = 0) -> dict[str, Any]:
        self.calls.append(text)
        return {"verdict_id": "vd_1"}


def test_message_allowlist_blocks_real_domains_in_any_form() -> None:
    ok = [
        "see falcon-demo-bank.test/pay",
        "visit https://a.example/x now",
        "mail me@corp.invalid",
        "no links at all, 3.5 e.g.",
    ]
    bad = [
        "go to evil-site.com now",
        "hxxps://bank-login[.]net/x",
        "write to someone@gmail.com",
        "https://falcon-demo-bank.test.evil.org/",
        "mixed falcon-demo-bank.test and paypa1.com",
        "بنك الصقر: افتح bad-link.ae الآن",
    ]
    assert all(corpus.message_allowed(t) for t in ok)
    assert not any(corpus.message_allowed(t) for t in bad)


def test_item_gate_drops_redteam_and_offlist_urls_and_seed_blocks_them() -> None:
    assert not corpus.item_allowed(corpus.Item("redteam", "url", "https://evil.example.com/"))
    assert not corpus.item_allowed(corpus.Item("fixture", "url", "https://real-brand.com/"))
    assert not corpus.item_allowed(corpus.Item("message", "message", "click evil.com"))
    assert not hasattr(corpus, "redteam_items")
    client = FakeClient()
    items = [
        corpus.Item("redteam", "url", "https://evil.example.com/"),
        corpus.Item("message", "message", "x evil.com"),
    ]
    s = seed.run_seed(items, client, None, state={}, rate_per_s=0)  # type: ignore[arg-type]
    assert not client.calls and sum(s.blocked.values()) == 2
    assert "evil" not in s.render()  # counts only, never contents


def test_messages_are_never_rewritten_and_corpus_has_no_redteam(tmp_path: Path) -> None:
    (tmp_path / "synthetic_messages_x.jsonl").write_text(json.dumps({"text": "hxxps://a[.]example/"}) + "\n")
    assert corpus.message_items(tmp_path, limit=None)[0].value == "hxxps://a[.]example/"
    assert all(i.group != "redteam" for i in corpus.build_corpus()[0])


CFG = {
    "name": "p1",
    "volumes": {"pg_data": {"name": "p1_pg_data"}, "redis_data": {"name": "p1_redis_data"}},
}


def test_reset_plan_uses_compose_config_names() -> None:
    assert ops.reset_plan(CFG) == ("p1", ["p1_pg_data", "p1_redis_data"])
    with pytest.raises(ValueError):
        ops.reset_plan({"name": "x", "volumes": {}})
    with pytest.raises(ValueError):
        ops.reset_plan({})


def test_demo_reset_prompts_with_exact_names_and_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "compose_config", lambda: CFG)
    ran: list[Any] = []
    monkeypatch.setattr(ops.subprocess, "run", lambda *a, **k: ran.append(a))
    msgs: list[str] = []
    assert ops.demo_reset(False, msgs.append, ask=lambda _: "nope") == 1
    assert "p1_pg_data" in msgs[0] and "p1_redis_data" in msgs[0] and not ran
    monkeypatch.setattr(ops, "PRIVATE_DIR", Path("/nonexistent-falcon-test"))
    assert ops.demo_reset(True, msgs.append) == 0
    assert ["docker", "volume", "rm", "-f", "p1_pg_data", "p1_redis_data"] in [a[0] for a in ran]


def test_demo_reset_refuses_when_config_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> dict[str, object]:
        raise ValueError("no docker")

    monkeypatch.setattr(ops, "compose_config", boom)
    assert ops.demo_reset(True, lambda _: None) == 1


def test_tunnel_stop_garbled_and_foreign_pid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pidf = tmp_path / "t.pid"
    monkeypatch.setattr(ops, "TUNNEL_PID_FILE", pidf)
    monkeypatch.setattr(ops, "TUNNEL_URL_FILE", tmp_path / "u.txt")
    killed: list[int] = []
    monkeypatch.setattr(ops.os, "kill", lambda pid, sig: killed.append(pid))
    msgs: list[str] = []
    pidf.write_text("not-a-pid\n")
    assert ops.tunnel_stop(msgs.append) == 0 and "garbled" in msgs[-1] and not pidf.exists()
    pidf.write_text("4242")
    monkeypatch.setattr(ops, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(ops, "_pid_is_cloudflared", lambda pid: False)
    ops.tunnel_stop(msgs.append)
    assert not killed and "not a running cloudflared" in msgs[-1]
    pidf.write_text("4242")
    monkeypatch.setattr(ops, "_pid_is_cloudflared", lambda pid: True)
    ops.tunnel_stop(msgs.append)
    assert killed == [4242]
