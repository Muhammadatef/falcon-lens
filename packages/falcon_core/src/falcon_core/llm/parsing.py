"""Extract one JSON object from model text and validate it with pydantic."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from falcon_core.llm.providers import strip_special_tokens

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class ParseError(ValueError):
    """The text held no valid object for the schema. ``summary`` is safe to show the model."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


def extract_json_object(text: str) -> dict[str, Any]:
    text = strip_special_tokens(text)
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start < 0:
        raise ParseError("no JSON object found")
    try:
        obj, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ParseError("top-level value must be an object")
    return obj


def parse_model[T: BaseModel](
    text: str, schema: type[T], context: Mapping[str, Any] | None = None
) -> T:
    obj = extract_json_object(text)
    try:
        return schema.model_validate(obj, context=dict(context) if context else None)
    except ValidationError as exc:
        parts = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(x) for x in err.get("loc", ())) or "(root)"
            parts.append(f"{loc}: {err.get('type', 'invalid')}")
        raise ParseError("schema violation: " + "; ".join(parts)) from exc
