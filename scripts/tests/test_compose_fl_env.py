"""docker-compose.yml must never default FL_ENV (a forgotten FL_ENV must fail, not become `local`)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
REF = re.compile(r"\$\{FL_ENV(?P<op>[^}]*)\}")


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings(k) + _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def test_every_fl_env_reference_is_required() -> None:
    refs = [m.group("op") for s in _strings(yaml.safe_load(COMPOSE.read_text())) for m in REF.finditer(s)]
    assert refs, "expected FL_ENV references in docker-compose.yml"
    bad = [op for op in refs if not op.startswith(":?")]
    assert not bad, f"FL_ENV must use ${{FL_ENV:?message}} with no default, found {bad}"


def test_no_bare_or_defaulted_fl_env_in_raw_text() -> None:
    text = COMPOSE.read_text()
    assert not re.search(r"\$\{FL_ENV:?-", text)
    assert not re.search(r"\$FL_ENV\b", text)
