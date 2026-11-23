"""Padding on both sides of a message must never lower the message-text signals (fail closed)."""

from __future__ import annotations

import pytest

from falcon_core.signals.message.analyze import analyze_message

BASE = "Falcon Demo Bank security: urgent, send us the 6-digit code you just received or your card will be blocked."
WANT = ("message.scam_intent", "message.floor_pair")


@pytest.mark.parametrize("pad", [70_000, 130_000])
@pytest.mark.parametrize("junk", [".", "\n", "\u200b", "\x00"])
def test_padding_never_lowers_message_text_signals(pad: int, junk: str) -> None:
    want = {e.signal for e in analyze_message(BASE).evidence if e.signal in WANT}
    assert want
    got = {e.signal for e in analyze_message(junk * pad + " " + BASE + " " + junk * pad).evidence}
    assert want <= got
