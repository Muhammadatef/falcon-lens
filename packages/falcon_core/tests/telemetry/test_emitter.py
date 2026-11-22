from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from falcon_core.telemetry import metrics as m

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "emit_demo_metrics.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("emit_demo_metrics", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _samples(family: str, **match: str) -> float:
    total = 0.0
    for fam in m.REGISTRY.collect():
        if fam.name == family:
            for s in fam.samples:
                if all(s.labels.get(k) == v for k, v in match.items()):
                    total += s.value
    return total


def test_emitter_never_emits_eval_metric_and_never_live() -> None:
    mod = _load()
    eval_before = _samples("fl_eval_metric")
    live_before = _samples("fl_checks", source="live")
    incidents_live_before = _samples("fl_incidents", source="live")
    rng = random.Random(7)
    state = {"agree": 0.92, "drift": 0.05, "lag": 3.0}
    for _ in range(60):
        mod.tick(rng, state)
    assert _samples("fl_eval_metric") == eval_before
    assert _samples("fl_checks", source="live") == live_before
    assert _samples("fl_incidents", source="live") == incidents_live_before
    assert _samples("fl_checks", source="replay") > 0


def test_emitter_binds_loopback_by_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load()
    seen: dict[str, Any] = {}
    monkeypatch.setattr(mod, "start_http_server", lambda port, addr, registry: seen.update(addr=addr))
    monkeypatch.setattr(mod, "TARGETS", tmp_path / "targets.yml")
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.delenv("FL_DEMO_EMITTER_BIND", raising=False)
    monkeypatch.setattr(sys, "argv", ["emit", "--seconds", "0.01"])
    mod.main()
    assert seen["addr"] == "127.0.0.1"
    monkeypatch.setenv("FL_DEMO_EMITTER_BIND", "0.0.0.0")  # noqa: S104
    mod.main()
    assert seen["addr"] == "0.0.0.0"  # noqa: S104
