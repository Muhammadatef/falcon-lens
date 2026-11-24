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
