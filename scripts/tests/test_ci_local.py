"""Parity: every job in .github/workflows/ci.yml has a local equivalent in scripts/ci_local.py."""

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ci_local", ROOT / "scripts" / "ci_local.py")
assert _spec and _spec.loader
ci_local = importlib.util.module_from_spec(_spec)
sys.modules["ci_local"] = ci_local
_spec.loader.exec_module(ci_local)


def _ci_jobs() -> set[str]:
    wf = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    return {j.get("name", k) for k, j in wf["jobs"].items()}


def test_every_ci_job_has_a_local_equivalent() -> None:
    assert _ci_jobs() == set(ci_local.JOBS), "ci.yml and scripts/ci_local.py JOBS drifted"


def test_every_job_declares_tools_and_a_script() -> None:
    for name, (tools, script) in ci_local.JOBS.items():
        assert tools and script.strip(), name


def test_docker_images_use_throwaway_namespace() -> None:
    assert ci_local.CI_IMAGE_NS == "falcon-lens-ci"
