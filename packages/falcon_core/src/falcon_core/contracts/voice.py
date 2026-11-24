"""Voice utterance response, mirrors contracts/voice.schema.json."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceUtterance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(max_length=300)
    lang: Literal["ar", "en", "other"]
    wake: bool
    intent: Literal["check_clipboard", "check_text", "help", "stop", "none"]
    command: str = Field(max_length=300)
    duration_ms: int = Field(ge=0)
    model: str


class SttResult(BaseModel):
    """What an STT engine (native or container) returns from POST /stt. Internal, not a public contract."""

    text: str
    lang: str | None = None
    ms: int = 0
    duration_ms: int = 0
    model: str = ""
