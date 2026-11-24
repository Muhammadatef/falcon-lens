"""VoiceUtterance mirrors contracts/voice.schema.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from falcon_core.contracts.voice import VoiceUtterance

SCHEMA = json.loads((Path(__file__).resolve().parents[4] / "contracts" / "voice.schema.json").read_text("utf-8"))
OK = {
    "transcript": "hey falcon",
    "lang": "en",
    "wake": True,
    "intent": "none",
    "command": "",
    "duration_ms": 1200,
    "model": "native:whisper-large-v3-turbo",
}


def test_roundtrip() -> None:
    Draft202012Validator(SCHEMA).validate(OK)
    assert VoiceUtterance.model_validate(OK).model_dump() == OK


def test_pydantic_matches_schema_fields() -> None:
    assert set(VoiceUtterance.model_fields) == set(SCHEMA["properties"]) == set(SCHEMA["required"])
    assert list(SCHEMA["properties"]["intent"]["enum"]) == list(
        VoiceUtterance.model_fields["intent"].annotation.__args__  # type: ignore[union-attr]
    )


@pytest.mark.parametrize(
    "bad",
    [{"transcript": "x" * 301}, {"lang": "fr"}, {"intent": "buy"}, {"duration_ms": -1}, {"extra": 1}],
)
def test_rejects_invalid(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VoiceUtterance.model_validate({**OK, **bad})
    assert list(Draft202012Validator(SCHEMA).iter_errors({**OK, **bad}))
