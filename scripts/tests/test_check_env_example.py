"""check_env_example.py rejects inline comments after values."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_env_example", Path(__file__).resolve().parent.parent / "check_env_example.py"
)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def test_flags_empty_value_with_comment() -> None:
    assert mod.problems("URLHAUS_AUTH_KEY=      # empty => feed disabled\n")


def test_flags_value_with_comment() -> None:
    assert mod.problems("FL_ENV=local   # local | demo\n")


def test_allows_own_line_comments_and_hash_in_value() -> None:
    assert not mod.problems("# note\nKEY=\nURL=http://a/b#frag\nFL_ENV=local\n")


def test_repo_env_example_is_clean() -> None:
    root = Path(__file__).resolve().parents[2]
    assert not mod.problems((root / ".env.example").read_text())
