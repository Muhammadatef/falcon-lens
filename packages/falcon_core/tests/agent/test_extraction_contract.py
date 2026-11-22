"""contracts/extraction.schema.json stays in sync with the pydantic ``Extraction`` model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from falcon_core.agent.extractor import Extraction, Language, RequestedData, ScriptCategory

SCHEMA_PATH = Path(__file__).resolve().parents[4] / "contracts" / "extraction.schema.json"
SCHEMA: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]


def test_enums_match_python() -> None:
    assert PROPS["requested_data"]["items"]["enum"] == [e.value for e in RequestedData]
    assert PROPS["script_category"]["enum"] == [e.value for e in ScriptCategory]
    assert PROPS["language"]["enum"] == [e.value for e in Language]


def test_fields_and_required_match_python() -> None:
    assert set(PROPS) == set(Extraction.model_fields)
    required = {n for n, f in Extraction.model_fields.items() if f.is_required()}
    assert set(SCHEMA["required"]) == required
    assert SCHEMA["additionalProperties"] is False


@pytest.mark.parametrize(
    ("obj", "valid"),
    [
        ({"script_category": "none", "language": "ar", "instruction_like": False}, True),
        ({"script_category": "none", "language": "ar", "instruction_like": False, "score": 0}, False),
        ({"script_category": "safe", "language": "ar", "instruction_like": False}, False),
        (
            {"requested_data": ["otp", "otp"], "script_category": "none", "language": "en", "instruction_like": True},
            False,
        ),
    ],
)
def test_schema_validates_like_model(obj: dict[str, Any], valid: bool) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    errors = list(jsonschema.Draft202012Validator(SCHEMA).iter_errors(obj))
    assert (not errors) is valid
