"""Voice hardening (audit 2026-11-24): silence/noise gate, prompt-echo guard, bank-caller rule, embedding keep-warm.

Each case reproduces a defect measured on the live stack: silence was transcribed as "Falcon Lens." (a false wake),
pink noise as «عدسة الصقر. هاي فالكون.» (a false wake that played a redirect), "someone called saying he is from the
bank" got the off-topic redirect, and the embedding model was unloaded after two idle minutes.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from collections.abc import Sequence

import httpx
import pytest

from falcon_core.voice.faq import match_rules
from falcon_core.voice.faq_semantic import DEFAULT_KEEP_ALIVE, FaqSemantic, ollama_embedder
from falcon_core.voice.guard import (
    clean_transcript,
    frame_stats,
    is_prompt_echo,
    is_sparse,
    speech_like,
)
from falcon_core.voice.intent import analyse

# --- signal gate -----------------------------------------------------------------------------


def speech_frames(seconds: float = 2.0, noise: float = 0.002) -> list[float]:
    """Syllable-like bursts (150 ms loud, 100 ms quiet) over a noise floor, then 0.8 s of trailing room noise."""
    out = []
    for i in range(int(seconds / 0.02)):
        loud = (i % 12) < 7
        out.append(0.15 if loud else noise)
    return out + [noise] * 40


def test_silence_and_flat_noise_are_not_speech() -> None:
    rng = random.Random(7)
    assert not speech_like([])
    assert not speech_like([0.0] * 150)  # digital silence
    assert not speech_like([0.0005] * 150)  # below the level floor
    assert not speech_like([0.012 * (1 + 0.2 * rng.uniform(-1, 1)) for _ in range(150)])  # quiet steady noise
    assert not speech_like([0.18 * (1 + 0.05 * rng.uniform(-1, 1)) for _ in range(150)])  # loud steady noise
    assert not speech_like([0.0884] * 750)  # a 15 s tone


def test_speech_passes_the_gate_even_in_a_noisy_room() -> None:
    assert speech_like(speech_frames())
    assert speech_like(speech_frames(noise=0.03))  # about 14 dB above the room
    assert speech_like(speech_frames(seconds=0.6))  # a bare "Hey Falcon"


def test_frame_stats_counts_voiced_seconds() -> None:
    p95, spread, voiced = frame_stats(speech_frames(seconds=2.4))
    assert p95 == pytest.approx(0.15)
    assert spread > 50
    assert 1.2 <= voiced <= 1.6  # 7 of every 12 frames of 2.4 s
    assert frame_stats([0.01] * 150)[2] == pytest.approx(3.0)  # steady noise is "voiced" all the way through


# --- transcript guards -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "عدسة الصقر. هاي فالكون.",
        "يا صقر. عدسة الصقر.",
        "Hey Falcon. Falcon Lens.",
        "Falcon Lens. Hey Falcon. Falcon Lens.",
    ],
)
def test_prompt_echo_is_dropped(text: str) -> None:
    assert is_prompt_echo(text)
    assert clean_transcript(text, 3.0) == ""
    assert analyse(clean_transcript(text, 3.0)).wake is False


@pytest.mark.parametrize(
    "text",
    ["Hey Falcon.", "يا صقر.", "Falcon Lens.", "عدسة الصقر", "Hey Falcon, check my messages", "يا صقر، افحص رسائلي"],
)
def test_one_wake_phrase_is_never_an_echo(text: str) -> None:
    assert not is_prompt_echo(text)
    assert clean_transcript(text, 2.0, (), 0.6) == text
    assert analyse(text).wake is True


@pytest.mark.parametrize("text", ["Thank you.", "ترجمة نانسي قنقر", "شكراً للمشاهدة", "اشتركوا في القناة", "you"])
def test_stock_hallucinations_are_dropped(text: str) -> None:
    assert clean_transcript(text, 3.0) == ""


def test_a_few_words_over_seconds_of_continuous_sound_is_dropped() -> None:
    assert is_sparse("عدسة الصقر.", 2.8)
    assert clean_transcript("عدسة الصقر.", 3.0, (), 2.8) == ""
    assert not is_sparse("Hey Falcon.", 0.5)
    assert not is_sparse("Hey Falcon, someone called saying he is from the bank.", 4.9)  # a real sentence
    assert clean_transcript("Hey Falcon.", 1.0, (), 0.5) == "Hey Falcon."
    assert clean_transcript("Hey Falcon.", 1.0) == "Hey Falcon."  # no measurement: unchanged behaviour


# --- the hook-video story: a caller who says he is the bank ------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "someone called saying he is from the bank",
        "I got a call from the bank",
        "a man phoned me and said he was a bank employee",
        "واحد اتصل علي يقول انه من البنك",
        "كلمني واحد من البنك",
        "دق علي واحد يقول إنه موظف البنك",
        "واحد اتصل غني وقال إنه من البنكويبي الرمز",  # Whisper's own spelling of the Arabic demo line
    ],
)
def test_bank_caller_gets_the_never_share_your_code_answer(text: str) -> None:
    assert match_rules(text) == "otp"
    r = analyse(f"Hey Falcon, {text}")
    assert (r.intent, r.answer_id) == ("faq", "otp")


@pytest.mark.parametrize("text", ["should I call my bank", "what is the weather today", "my bank is closed today"])
def test_bank_caller_rule_does_not_swallow_other_sentences(text: str) -> None:
    assert match_rules(text) != "otp"


# --- embedding model stays loaded ----------------------------------------------------------------


async def test_embedder_asks_ollama_to_keep_the_model_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    bodies: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await ollama_embedder("http://ollama.test:11434", client=client)(["a"])
    assert bodies[-1]["keep_alive"] == DEFAULT_KEEP_ALIVE == "24h"
    monkeypatch.setenv("FL_VOICE_EMBED_KEEP_ALIVE", "2h")
    await ollama_embedder("http://ollama.test:11434", client=client)(["a"])
    assert bodies[-1]["keep_alive"] == "2h"


class Slow:
    """Embedder whose single-text calls are slow while `cold` (an unloaded model), instant otherwise."""

    def __init__(self) -> None:
        self.cold = False
        self.calls: list[list[str]] = []

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.cold and len(texts) == 1:
            if texts[0] == "ping":
                self.cold = False  # the background ping is what reloads the model
            else:
                await asyncio.sleep(0.5)
        return [[math.cos(len(t)), math.sin(len(t))] for t in texts]


async def test_timeout_reports_its_outcome_and_reloads_the_model_in_the_background() -> None:
    emb = Slow()
    sem = FaqSemantic(emb, timeout_s=0.05, questions={"otp": ("abc",), "report": ("abcdefgh",)})
    assert await sem.match_outcome("abc") == (None, "warming")
    await asyncio.sleep(0.01)
    assert sem.ready
    assert await sem.match_outcome("abc") == ("otp", "hit")
    emb.cold = True
    assert await sem.match_outcome("abc") == (None, "timeout")
    await asyncio.sleep(0.01)  # the forced ping ran
    assert ["ping"] in emb.calls
    assert await sem.match_outcome("abc") == ("otp", "hit")  # the next question is answered again


async def test_keep_warm_pings_only_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = Slow()
    sem = FaqSemantic(emb, questions={"otp": ("abc",)})
    sem.keep_warm()  # first call embeds the bank
    await asyncio.sleep(0.01)
    assert sem.ready
    sem.keep_warm()  # fresh: nothing to do
    await asyncio.sleep(0.01)
    assert ["ping"] not in emb.calls
    monkeypatch.setattr("falcon_core.voice.faq_semantic.KEEP_WARM_EVERY_S", 0.0)
    sem.keep_warm()
    await asyncio.sleep(0.01)
    assert emb.calls.count(["ping"]) == 1
