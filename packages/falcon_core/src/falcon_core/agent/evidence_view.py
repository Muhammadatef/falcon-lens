"""Structured-only evidence view for the investigator and responder (never raw text).

Observed values are reduced to booleans, numbers and short "token-like" strings (ids, enum values,
domains, dates). Free text that could carry instructions is replaced with ``"<text>"``. URLs are
defanged. This is the only form in which those LLMs see evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from falcon_core.contracts.evidence import Evidence
from falcon_core.tools.util import defang

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:/\-\[\]+@=%]{1,80}$")
_URL_RE = re.compile(r"(?i)^(?:https?|hxxps?)://")
TEXT_PLACEHOLDER = "<text>"


def host_only(value: str) -> str:
    """Defanged ``scheme://host`` of a URL-like string: paths, queries and fragments (attacker-chosen
    text, e.g. CamelCase instructions in a QR link) never reach an LLM."""
    m = re.match(r"(?i)^((?:https?|hxxps?)://)?([^/?#\s]{1,100})", value)
    if m is None:
        return TEXT_PLACEHOLDER
    return defang(f"{m.group(1) or ''}{m.group(2)}")[:120]


def safe_value(value: Any, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if _URL_RE.match(value):
            return host_only(value)
        if "/" in value and _TOKEN_RE.match(value):
            return host_only(value)  # host/path token: keep the host only
        return value if _TOKEN_RE.match(value) else TEXT_PLACEHOLDER
    if depth >= 2:
        return TEXT_PLACEHOLDER
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:10]:
            key = str(k)
            if _TOKEN_RE.match(key):
                out[key[:40]] = safe_value(v, depth + 1)
        return out
    if isinstance(value, list | tuple):
        return [safe_value(v, depth + 1) for v in list(value)[:8]]
    return TEXT_PLACEHOLDER


def evidence_item(ev: Evidence, *, with_weight: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": ev.id,
        "signal": ev.signal,
        "family": ev.family,
        "observed": safe_value(ev.observed),
        "tier": ev.tier,
        "confidence": round(ev.confidence, 2),
    }
    if ev.error:
        item["error"] = True
    if with_weight:
        item["weight"] = round(ev.weight, 2)
        if ev.hard_rule:
            item["hard_rule"] = ev.hard_rule
    return item


def evidence_json(evidence: Sequence[Evidence], *, with_weight: bool = False, limit: int = 60) -> str:
    items = [evidence_item(e, with_weight=with_weight) for e in evidence[:limit]]
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"))
