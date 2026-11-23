"""The Anthropic client never records content in spans and never sends a traceparent."""

from __future__ import annotations

import pytest

from falcon_core.llm.providers import ANTHROPIC_OTEL_OPTION, AnthropicProvider


def test_client_options_are_metadata_only_without_propagation() -> None:
    assert ANTHROPIC_OTEL_OPTION == {
        "traces": {"enabled": True, "content_mode": "metadata_only"},
        "propagation": False,
    }
    client = AnthropicProvider("sk-test")._client
    assert client.open_telemetry["traces"]["content_mode"] == "metadata_only"
    assert client.open_telemetry["propagation"] is False


def test_env_content_mode_cannot_enable_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE", "content")
    client = AnthropicProvider("sk-test")._client
    assert client.open_telemetry["traces"]["content_mode"] == "metadata_only"
