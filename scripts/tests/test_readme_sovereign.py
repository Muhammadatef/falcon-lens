"""README and ARCHITECTURE statements about the sovereign-mode proof match the published artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = sorted((ROOT / "evals/results/published/sovereign").glob("sovereign_*.json"))
NUMBER_WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}


def _runs() -> list[dict[str, object]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in ARTIFACTS]


def test_docs_do_not_call_the_proof_pending_once_artifacts_exist() -> None:
    assert ARTIFACTS, "no sovereign proof artifact is published"
    for name in ("README.md", "docs/ARCHITECTURE.md", "docs/INTEGRATION.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not re.search(r"sovereign-mode proof (run )?(is )?pending|proof pending", text, re.I), name
        assert "evals/results/published/sovereign" in text, name


def test_readme_run_counts_come_from_the_artifacts() -> None:
    runs = _runs()
    passed = sum(1 for r in runs if r["status"] == "passed")
    failed = sum(1 for r in runs if r["status"] == "failed")
    assert passed + failed == len(runs)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{NUMBER_WORDS[len(runs)]} fresh-stack runs are published" in readme
    assert f"{NUMBER_WORDS[passed]} of the {NUMBER_WORDS[len(runs)].lower()} runs is recorded as `passed`" in readme
    assert f"the other {NUMBER_WORDS[failed].lower()} are recorded as `failed`" in readme
    # "seven demo scenarios passed in all four" must hold for every artifact.
    assert all(r["scenario_counts"] == {"PASS": 7} for r in runs)
    # Every logged, successful LLM call used the local route.
    for r in runs:
        calls = r["llm_calls_from_logs"]["ok_calls"]  # type: ignore[index]
        assert calls and all(c["route"] == "local" for c in calls)


def test_readme_qwen_row_matches_the_qwen_artifacts() -> None:
    qwen = [r for r in _runs() if "qwen3.8" in str(r["local_model"])]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith("| `qwen3.8:27b`"))
    assert f"{len(qwen)} runs published" in row
    assert all(r["status"] == "failed" for r in qwen) and "both recorded as `failed`" in row
