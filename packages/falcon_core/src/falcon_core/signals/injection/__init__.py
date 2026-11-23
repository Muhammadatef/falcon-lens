"""Prompt-injection detection: ``injection.instruction_like_text`` (risk evidence only, never obeyed)."""

from falcon_core.signals.injection.detector import (
    HIDDEN_CHANNELS,
    REMOVED,
    SIGNAL,
    SPEC,
    Channel,
    Finding,
    InjectionReport,
    Segment,
    detect,
    neutralise,
)

__all__ = [
    "HIDDEN_CHANNELS",
    "REMOVED",
    "SIGNAL",
    "SPEC",
    "Channel",
    "Finding",
    "InjectionReport",
    "Segment",
    "detect",
    "neutralise",
]
