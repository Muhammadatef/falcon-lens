"""Frozen DSPy-compiled prompts (ADR-002). Production loads JSON only and never imports dspy.

`evals/dspy/optimize.py` (make dspy-optimize) writes `<name>.json` next to this file. The same instructions and
few-shot demos are sent on BOTH routes (Claude or the local model); the router only changes the model.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

NAMES = ("incident_summary", "scam_script")
_DIR = Path(__file__).parent


class CompiledPromptError(Exception):
    """Missing file, unknown name or content hash mismatch (the frozen file was edited by hand)."""


def content_sha256(instructions: str, demos: list[dict[str, Any]]) -> str:
    blob = json.dumps({"instructions": instructions, "demos": demos}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class CompiledPrompt:
    name: str
    instructions: str
    demos: list[dict[str, Any]]
    inputs: list[str]
    outputs: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def render_system(self, max_demos: int | None = None) -> str:
        """System prompt text: optimised instructions followed by the frozen few-shot examples."""
        parts = [self.instructions.strip()]
        demos = self.demos if max_demos is None else self.demos[:max_demos]
        for i, d in enumerate(demos, 1):
            parts.append(
                f"Example {i}\nINPUT:\n{json.dumps(d['inputs'], ensure_ascii=False, sort_keys=True)}\n"
                f"OUTPUT:\n{json.dumps(d['outputs'], ensure_ascii=False, sort_keys=True)}"
            )
        return "\n\n".join(parts)


@lru_cache(maxsize=8)
def load(name: str) -> CompiledPrompt:
    if name not in NAMES:
        raise CompiledPromptError(f"unknown compiled prompt {name!r}; expected one of {NAMES}")
    path = _DIR / f"{name}.json"
    if not path.is_file():
        raise CompiledPromptError(f"{path.name} not found: run `make dspy-optimize` and commit the result")
    raw = json.loads(path.read_text(encoding="utf-8"))
    instructions, demos = str(raw["instructions"]), list(raw["demos"])
    if raw.get("content_sha256") != content_sha256(instructions, demos):
        raise CompiledPromptError(f"{path.name}: content_sha256 mismatch (edited by hand?)")
    return CompiledPrompt(
        name=name,
        instructions=instructions,
        demos=demos,
        inputs=list(raw["inputs"]),
        outputs=list(raw["outputs"]),
        metadata=dict(raw.get("metadata", {})),
    )
