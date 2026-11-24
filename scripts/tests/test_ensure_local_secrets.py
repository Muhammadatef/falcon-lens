"""ensure_local_secrets fills only empty local secrets, keeps existing values, never touches cloud keys."""

from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("els", Path(__file__).parents[1] / "ensure_local_secrets.py")
assert spec and spec.loader
els = importlib.util.module_from_spec(spec)
spec.loader.exec_module(els)


def test_fills_empty_keeps_existing_and_cloud_keys(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\nPHOENIX_SECRET=\nPHOENIX_ADMIN_SECRET=keepme-already-set\n", encoding="utf-8")
    assert els.main(str(env)) == 0
    out = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines() if "=" in line)
    assert out["ANTHROPIC_API_KEY"] == ""
    assert out["PHOENIX_ADMIN_SECRET"] == "keepme-already-set"
    assert len(out["PHOENIX_SECRET"]) >= 32
    assert len(out["PHOENIX_ADMIN_INITIAL_PASSWORD"]) >= 32
    assert out["PHOENIX_SECRET"] != out["PHOENIX_ADMIN_INITIAL_PASSWORD"]


def test_idempotent(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("PHOENIX_SECRET=\n", encoding="utf-8")
    els.main(str(env))
    first = env.read_text(encoding="utf-8")
    els.main(str(env))
    assert env.read_text(encoding="utf-8") == first


def test_example_env_has_these_keys_empty() -> None:
    example = (Path(__file__).parents[2] / ".env.example").read_text(encoding="utf-8")
    for name in els.LOCAL_ONLY:
        assert f"\n{name}=\n" in example


def test_secret_always_meets_phoenix_rule(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    values = iter(["A" * 48, "abcdefghijklmnopqrstuvwxyzabcdefghij", "abc1" * 12])
    monkeypatch.setattr(els.secrets, "token_urlsafe", lambda n: next(values))
    assert els.new_secret() == "abc1" * 12
    monkeypatch.undo()
    for _ in range(2000):
        v = els.new_secret()
        assert len(v) >= 32 and any(c.isdigit() for c in v) and any(c.islower() for c in v)


def test_every_stack_start_path_fills_secrets() -> None:
    root = Path(__file__).parents[2]
    make = (root / "Makefile").read_text(encoding="utf-8")
    for target in ("up:", "demo:"):
        body = make.split("\n" + target, 1)[1].split("\n\n", 1)[0]
        assert "ensure_local_secrets.py" in body.split("up -d")[0], target
    smoke = (root / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    start = smoke.split("stack not up, starting it", 1)[1]
    assert start.index("ensure_local_secrets.py") < start.index("up -d")


def test_evidence_hmac_key_is_generated_locally(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("FL_EVIDENCE_HMAC_KEY=\n", encoding="utf-8")
    els.main(str(env))
    out = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines() if "=" in line)
    assert "FL_EVIDENCE_HMAC_KEY" in els.LOCAL_ONLY and len(out["FL_EVIDENCE_HMAC_KEY"]) >= 32
