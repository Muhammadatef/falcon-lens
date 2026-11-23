"""scripts/compose_hardening.py on synthetic compose configs (no Docker needed)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_P = Path(__file__).resolve().parents[1] / "compose_hardening.py"
_spec = importlib.util.spec_from_file_location("compose_hardening", _P)
assert _spec and _spec.loader
ch = importlib.util.module_from_spec(_spec)
sys.modules["compose_hardening"] = ch
_spec.loader.exec_module(ch)

HARD: dict[str, Any] = {
    "read_only": True,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "user": "10001:10001",
    "mem_limit": "512m",
    "pids_limit": 256,
}


def cfg(**sandbox: Any) -> dict[str, Any]:
    return {
        "networks": {"sandbox": {"internal": True}, "app": {}},
        "services": {
            "sandbox": {**HARD, "networks": {"sandbox": {}}, **sandbox},
            "egress-proxy": {**HARD, "networks": {"sandbox": {}, "app": {}}},
            "fixtures": {**HARD, "networks": {"sandbox": {}}},
            "postgres": {"security_opt": ["no-new-privileges:true"], "networks": {"app": {}}},
        },
    }


def test_hardened_config_passes_and_stateful_services_only_warn() -> None:
    problems, notes = ch.check_config(cfg(), inspect_images=False)
    assert problems == []
    assert any("postgres: read_only" in n for n in notes)


def test_sandbox_violations_fail() -> None:
    for patch, needle in [
        ({"read_only": False}, "read_only"),
        ({"cap_drop": []}, "cap_drop"),
        ({"security_opt": []}, "no-new-privileges"),
        ({"user": "root"}, "runs as root"),
        ({"user": "0:0"}, "runs as root"),
        ({"pids_limit": None}, "pids_limit"),
        ({"mem_limit": None}, "memory limit"),
        ({"networks": {"app": {}}}, "non-internal network"),
        ({"ports": [{"target": 8080}]}, "publishes host ports"),
        ({"privileged": True}, "privileged"),
        ({"volumes": [{"source": "/var/run/docker.sock"}]}, "Docker socket"),
    ]:
        problems, _ = ch.check_config(cfg(**patch), inspect_images=False)
        assert any(needle in p for p in problems), (patch, problems)


def test_saved_json_cli(tmp_path: Path) -> None:
    import json

    f = tmp_path / "c.json"
    f.write_text(json.dumps(cfg(read_only=False)))
    assert ch.main(["--compose-json", str(f), "--no-inspect"]) == 1
    f.write_text(json.dumps(cfg()))
    assert ch.main(["--compose-json", str(f), "--no-inspect"]) == 0
