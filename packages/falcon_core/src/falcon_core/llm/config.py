"""Router configuration, read from the process environment only (never from a .env file here).

Variables (.env.example): ``FL_SOVEREIGN_MODE``, ``ANTHROPIC_API_KEY``, ``FL_CLOUD_MODEL_<ROLE>``,
``FL_LLM_TIMEOUT_S``, ``OLLAMA_BASE_URL``, ``FL_LOCAL_MODEL``, ``FL_LOCAL_VISION_MODEL``,
``FL_LOCAL_LLM_TIMEOUT_S``, ``FL_SHADOW_RATE``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

Role = Literal["extractor", "investigator", "responder", "vision", "sentinel", "judge"]
ROLES: tuple[Role, ...] = ("extractor", "investigator", "responder", "vision", "sentinel", "judge")
Route = Literal["cloud", "local"]

DEFAULT_CLOUD_MODELS: dict[Role, str] = {
    "extractor": "claude-haiku-5-5",
    "investigator": "claude-sonnet-5-5",
    "responder": "claude-haiku-5-5",
    "vision": "claude-sonnet-5-5",
    "sentinel": "claude-sonnet-5-5",
    "judge": "claude-sonnet-5-5",
}
DEFAULT_LOCAL_MODEL = "inkling-2-mini-chat"
DEFAULT_LOCAL_VISION_MODEL = "gemma3:27b"


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _float(v: str | None, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class RouterConfig:
    sovereign_mode: bool = False
    anthropic_api_key: str | None = field(default=None, repr=False)
    cloud_models: Mapping[Role, str] = field(default_factory=lambda: dict(DEFAULT_CLOUD_MODELS))
    local_model: str = DEFAULT_LOCAL_MODEL
    local_vision_model: str = DEFAULT_LOCAL_VISION_MODEL
    ollama_base_url: str = "http://host.docker.internal:11434"
    cloud_timeout_s: float = 12.0
    local_timeout_s: float = 60.0
    shadow_rate: float = 0.0

    @property
    def cloud_enabled(self) -> bool:
        """Cloud only with a key and outside sovereign mode."""
        return bool(self.anthropic_api_key) and not self.sovereign_mode

    def local_model_for(self, role: Role) -> str:
        return self.local_vision_model if role == "vision" else self.local_model

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> RouterConfig:
        e = os.environ if env is None else env
        cloud = dict(DEFAULT_CLOUD_MODELS)
        for role in ROLES:
            v = e.get(f"FL_CLOUD_MODEL_{role.upper()}")
            if v:
                cloud[role] = v
        rate = min(1.0, max(0.0, _float(e.get("FL_SHADOW_RATE"), 0.0)))
        return cls(
            sovereign_mode=_truthy(e.get("FL_SOVEREIGN_MODE")),
            anthropic_api_key=e.get("ANTHROPIC_API_KEY") or None,
            cloud_models=cloud,
            local_model=e.get("FL_LOCAL_MODEL") or DEFAULT_LOCAL_MODEL,
            local_vision_model=e.get("FL_LOCAL_VISION_MODEL") or DEFAULT_LOCAL_VISION_MODEL,
            ollama_base_url=e.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434",
            cloud_timeout_s=_float(e.get("FL_LLM_TIMEOUT_S"), 12.0),
            local_timeout_s=_float(e.get("FL_LOCAL_LLM_TIMEOUT_S"), 60.0),
            shadow_rate=rate,
        )
