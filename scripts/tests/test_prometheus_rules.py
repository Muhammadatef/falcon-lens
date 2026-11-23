"""promtool unit tests for the alert rules (infra/prometheus/tests/*.test.yml)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROM = ROOT / "infra" / "prometheus"
IMAGE = "prom/prometheus:v3.16.0"


def _run(test_file: Path) -> subprocess.CompletedProcess[str]:
    if shutil.which("promtool"):
        cmd = ["promtool", "test", "rules", str(test_file)]
    elif shutil.which("docker"):
        cmd = [
            "docker", "run", "--rm", "--entrypoint", "promtool", "-v", f"{PROM}:/p:ro", IMAGE,
            "test", "rules", f"/p/tests/{test_file.name}",
        ]  # fmt: skip
    else:
        pytest.skip("neither promtool nor docker is available")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180, check=False)  # noqa: S603


@pytest.mark.parametrize("test_file", sorted((PROM / "tests").glob("*.test.yml")), ids=lambda p: p.name)
def test_alert_rule_unit_tests_pass(test_file: Path) -> None:
    r = _run(test_file)
    if r.returncode != 0 and "Unable to find image" in r.stderr:
        pytest.skip("promtool image not available offline")
    assert r.returncode == 0, r.stdout + r.stderr


def test_eval_regression_reads_the_exporter_labels() -> None:
    text = (PROM / "rules" / "falcon-alerts.yml").read_text(encoding="utf-8")
    block = text.split("alert: EvalRegression", 1)[1].split("alert: ScoreDrift", 1)[0]
    assert (
        'source="main"' in block
        and "fl_eval_artifact_latest" in block
        and "runbook_url: docs/RUNBOOK.md#eval-regression" in block
    )
    assert "name=~" not in block  # the old registry-gauge label that nothing populated
