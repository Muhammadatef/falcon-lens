"""Small helpers shared by tools and agents: evidence ids, defanging, evidence hygiene."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable
from typing import Any

from falcon_core.contracts.evidence import Evidence, Tier

IdFactory = Callable[[], str]
MAX_OBSERVED_STR = 512  # evidence.schema.json: strings max 512 chars
_URLISH_RE = re.compile(r"(?i)\b(?:https?|ftp)://")


def new_evidence_id() -> str:
    return "ev_" + secrets.token_hex(8)


def sequential_ids(prefix: str = "t") -> IdFactory:
    """Deterministic id factory for tests: ev_<prefix>0000001, ..."""
    n = 0
    p = re.sub(r"[^a-z0-9]", "", prefix.lower())[:8] or "t"

    def make() -> str:
        nonlocal n
        n += 1
        return f"ev_{p}{n:07d}"

    return make


def defang(text: str) -> str:
    """hxxp(s):// and [.] so URLs never render as live links."""
    out = re.sub(r"(?i)\bhttp(s?)://", r"hxxp\1://", text)
    out = re.sub(r"(?i)\bftp://", "fxp://", out)
    return out.replace(".", "[.]")


def _clip_observed(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        v = defang(value) if _URLISH_RE.search(value) else value
        return v[:MAX_OBSERVED_STR]
    if depth >= 4:
        return None
    if isinstance(value, dict):
        return {str(k)[:64]: _clip_observed(v, depth + 1) for k, v in list(value.items())[:32]}
    if isinstance(value, list | tuple):
        return [_clip_observed(v, depth + 1) for v in list(value)[:32]]
    return value


def restamp(ev: Evidence, *, tier: Tier, new_id: str | None = None) -> Evidence:
    """Normalise evidence a tool returned: arbiter-owned fields cleared, strings capped.

    ``weight`` and ``hard_rule`` belong to the arbiter, so a tool (or anything behind it) can never
    pre-set them. ``polarity`` is reset too; the arbiter assigns it.
    """
    return ev.model_copy(
        update={
            "id": new_id or ev.id,
            "tier": tier,
            "weight": 0.0,
            "hard_rule": None,
            "polarity": "neutral",
            "observed": _clip_observed(ev.observed),
        }
    )
