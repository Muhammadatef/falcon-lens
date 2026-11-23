"""Compiled-prompt loader: checksum, fallback to the hand-written prompt, per-route use in the router."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from falcon_core.llm.config import RouterConfig
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.llm.testing import ScriptedProvider
from falcon_core.prompts import compiled as C

CANARY = "FLC-0123456789ab"


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str


def _write(
    dirpath: Path, name: str, route: str, instructions: str, demos: list[dict[str, Any]], sha: str | None = None
) -> None:
    body = {
        "schema_version": 2,
        "name": name,
        "route": route,
        "inputs": ["request"],
        "outputs": ["reply_json"],
        "instructions": instructions,
        "demos": demos,
        "content_sha256": sha or C.content_sha256(instructions, demos),
        "metadata": {},
    }
    (dirpath / f"{name}.{route}.json").write_text(json.dumps(body), encoding="utf-8")


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(C, "_DIR", tmp_path)
    C.load.cache_clear()
    yield tmp_path
    C.load.cache_clear()


def test_load_verifies_and_renders(store: Path) -> None:
    demo = {"inputs": {"request": "IN"}, "outputs": {"reply_json": '{"label":"x"}'}}
    _write(store, "extractor", "local", "Be precise.", [demo])
    cp = C.load("extractor", "local")
    assert cp.route == "local" and "Be precise." in cp.render_system() and "IN" in cp.render_system()


def test_checksum_mismatch_raises_and_falls_back(store: Path) -> None:
    _write(store, "extractor", "local", "Edited by hand", [], sha="0" * 64)
    with pytest.raises(C.CompiledPromptError, match="sha256"):
        C.load("extractor", "local")
    assert C.task_text("extractor", "local", "HAND") == "HAND"


def test_missing_unknown_and_garbage_fall_back(store: Path) -> None:
    assert C.task_text("extractor", "local", "HAND") == "HAND"  # file missing
    assert C.task_text("nope", "local", "HAND") == "HAND"  # unknown name
    assert C.task_text(None, "local", "HAND") == "HAND"
    (store / "investigator.local.json").write_text("{not json", encoding="utf-8")
    assert C.task_text("investigator", "local", "HAND") == "HAND"
    (store / "investigator.cloud.json").write_text('{"instructions": 1}', encoding="utf-8")
    assert C.task_text("investigator", "cloud", "HAND") == "HAND"


def test_prompt_is_route_specific(store: Path) -> None:
    _write(store, "extractor", "local", "LOCAL-COMPILED", [])
    assert C.task_text("extractor", "local", "HAND") == "LOCAL-COMPILED"
    assert C.task_text("extractor", "cloud", "HAND") == "HAND"  # no cloud file: hand-written stays


def _system_sent(compiled: str | None) -> str:
    local = ScriptedProvider("local", ['{"label": "ok"}'])
    router = LLMRouter(RouterConfig(), local=local, canary=CANARY)
    req: JsonRequest[Out] = JsonRequest(
        role="extractor", task="HAND-WRITTEN", schema=Out, context="ctx", compiled=compiled
    )
    res = asyncio.run(router.complete_json(req))
    assert res.ok
    return str(local.requests[0].system)


def test_router_uses_compiled_on_matching_route_only(store: Path) -> None:
    _write(store, "extractor", "local", "LOCAL-COMPILED", [])
    assert "LOCAL-COMPILED" in _system_sent("extractor")
    assert "HAND-WRITTEN" in _system_sent(None)
    (store / "extractor.local.json").write_text("garbage", encoding="utf-8")
    C.load.cache_clear()
    system = _system_sent("extractor")
    assert "HAND-WRITTEN" in system and "never decide or change a risk score" in system  # base rules stay


def test_shipped_files_verify() -> None:
    """Every compiled file committed to the repo loads and passes its checksum."""
    C.load.cache_clear()
    for p in sorted(Path(C.__file__).parent.glob("*.json")):
        name, route = p.name.removesuffix(".json").rsplit(".", 1)
        assert C.load(name, route).instructions
