"""build_ai wires the AI agents, and the website capability flags follow that wiring (no stale flags)."""

from __future__ import annotations

from typing import Any

import pytest

from falcon_core.agent import Investigator
from falcon_core.cascade.ai import AgentExtractorAdapter
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_worker import ai


class _Metrics:
    def inc(self, *_a: Any, **_k: Any) -> None: ...

    def observe(self, *_a: Any, **_k: Any) -> None: ...


class _Router:
    """Stub router: build_ai only stores it; no model call happens at build time."""

    metrics = _Metrics()


def _build(monkeypatch: pytest.MonkeyPatch, enabled: str) -> Any:
    monkeypatch.setenv("FL_AI_ENABLED", enabled)
    monkeypatch.setenv("FL_T1_MODEL_ENABLED", "false")
    monkeypatch.setattr(ai, "LLMRouter", _Router)
    registry = BrandRegistry.from_entries([])
    return ai.build_ai(http=None, cache=None, mirror=None, registry=registry, sandbox=None)  # type: ignore[arg-type]


def test_build_ai_wires_extractor_and_investigator(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _build(monkeypatch, "true")
    assert isinstance(out["extractor"], AgentExtractorAdapter)
    assert isinstance(out["investigator"], Investigator)


def test_build_ai_off_wires_no_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _build(monkeypatch, "false")
    assert "extractor" not in out and "investigator" not in out


def test_capability_flags_match_build_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails if build_ai wires an agent while its flag is false, or the flag is true while it is not wired."""
    from submission import capabilities as c

    monkeypatch.setenv("FL_PROBE_EXISTS_ONLY", "1")  # already inside pytest: a test: probe checks existence only
    out = _build(monkeypatch, "true")
    flags = {
        cap.id: all(c.probe(c.ROOT, s) for s in cap.probes if not s.startswith("gate:"))
        for cap in c.CAPABILITIES
        if cap.id in ("investigator", "injection_defence")
    }
    assert flags["investigator"] is ("investigator" in out)
    assert flags["injection_defence"] is ("extractor" in out)
