"""Tests for scripts/readme_stack.py: the README badge block lists only shipped tools."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "readme_stack.py"
_spec = importlib.util.spec_from_file_location("readme_stack", SCRIPT)
assert _spec and _spec.loader
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)


def test_readme_block_is_current() -> None:
    block = rs.render()
    assert rs.apply(rs.README.read_text(encoding="utf-8"), block) == rs.README.read_text(encoding="utf-8")


def test_unshipped_tools_are_not_listed() -> None:
    block = rs.render().lower()
    for name in ("dspy", "scikit", "langchain_core", "adp", "abu dhabi"):
        assert name not in block


def test_never_claims_safe_and_has_licence_badge() -> None:
    block = rs.render()
    assert "License" in block
    assert "safe" not in block.lower()


def test_apply_requires_markers() -> None:
    try:
        rs.apply("no markers", "x")
    except SystemExit:
        return
    raise AssertionError("expected SystemExit")
