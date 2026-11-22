"""Tests for scripts/readme_metrics.py: numbers reach the README only from artifacts."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "readme_metrics.py"
_spec = importlib.util.spec_from_file_location("readme_metrics", SCRIPT)
assert _spec and _spec.loader
rm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rm)

README = f"# Title\n\n## Evaluation\n{rm.START}\nold text 99%\n{rm.END}\n\n## Next\n"


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_no_artifact_prints_placeholder_and_no_digits(tmp_path: Path) -> None:
    block = rm.render(tmp_path / "published")
    assert rm.NO_ARTIFACT in block
    assert not any(ch.isdigit() for ch in block)


def test_values_are_copied_verbatim(tmp_path: Path) -> None:
    published = tmp_path / "published"
    _write(
        published / "20261123T140000Z.json",
        {
            "git_sha": "abc1234",
            "dataset_hash": "sha256:feed",
            "models": {"cloud": "model-a", "local": "model-b"},
            "metrics": {"validation": {"cloud": {"recall": 0.9137, "ci": [0.88, 0.94]}}},
        },
    )
    block = rm.render(published, root=tmp_path)
    assert "| `validation.cloud.recall` | 0.9137 |" in block
    assert "| `validation.cloud.ci` | [0.88, 0.94] |" in block
    assert "| `git_sha` | `abc1234` |" in block
    assert "| `models.local` | `model-b` |" in block
    assert "published/20261123T140000Z.json" in block


def test_newest_artifact_wins(tmp_path: Path) -> None:
    published = tmp_path / "published"
    _write(published / "20261123T140000Z.json", {"metrics": {"recall": 0.5}})
    _write(published / "20261124T090000Z.json", {"metrics": {"recall": 0.75}})
    block = rm.render(published, root=tmp_path)
    assert "0.75" in block
    assert "0.5 " not in block


def test_artifact_without_metrics_shows_no_numbers(tmp_path: Path) -> None:
    published = tmp_path / "published"
    _write(published / "a.json", {"thresholds": {"tau_high": 0.8}})
    block = rm.render(published, root=tmp_path)
    assert "no `metrics` object" in block
    assert "0.8" not in block


def test_inject_replaces_only_the_block() -> None:
    out = rm.inject(README, "NEW")
    assert out == f"# Title\n\n## Evaluation\n{rm.START}\nNEW\n{rm.END}\n\n## Next\n"
    assert rm.inject(out, "NEW") == out


def test_inject_requires_both_markers() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        rm.inject("# no markers", "x")


def test_main_writes_then_check_passes_and_detects_staleness(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    published = tmp_path / "published"
    args = ["--readme", str(readme), "--published", str(published)]

    assert rm.main([*args, "--check"]) == 1
    assert rm.main(args) == 0
    assert rm.NO_ARTIFACT in readme.read_text(encoding="utf-8")
    assert "99%" not in readme.read_text(encoding="utf-8")
    assert rm.main([*args, "--check"]) == 0

    _write(published / "b.json", {"metrics": {"fpr": 0.0125}})
    assert rm.main([*args, "--check"]) == 1
    assert rm.main(args) == 0
    assert "| `fpr` | 0.0125 |" in readme.read_text(encoding="utf-8")


def test_repo_readme_block_is_current() -> None:
    """The committed README must match what the script would write."""
    assert rm.main(["--check"]) == 0


def test_known_metrics_get_a_plain_sentence_without_digits(tmp_path: Path) -> None:
    published = tmp_path / "published"
    _write(
        published / "a.json",
        {"metrics": {"test": {"recall": 0.9, "recall_ci95": [0.8, 1.0], "custom": 3}}},
    )
    block = rm.render(published, root=tmp_path)
    assert f"| `test.recall` | 0.9 | {rm.PLAIN['recall']} |" in block
    assert f"| `test.recall_ci95` | [0.8, 1.0] | {rm.PLAIN_CI} |" in block
    assert "| `test.custom` | 3 |  |" in block
    for sentence in (*rm.PLAIN.values(), rm.PLAIN_CI):
        assert not any(ch.isdigit() for ch in sentence)
        assert "%" not in sentence


def test_scope_and_not_evaluated_are_shown_verbatim(tmp_path: Path) -> None:
    published = tmp_path / "published"
    _write(
        published / "a.json",
        {"scope": "first stage only", "not_evaluated": ["zero_day", "llm"], "metrics": {"n": 5}},
    )
    block = rm.render(published, root=tmp_path)
    assert "| `scope` | `first stage only` |" in block
    assert "Not evaluated in this artifact" in block
    assert "`zero_day`, `llm`" in block
