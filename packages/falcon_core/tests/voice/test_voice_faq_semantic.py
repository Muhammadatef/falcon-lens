"""Semantic FAQ fallback with a fake embedder (hashed bag of words): threshold, timeout, caching, failure paths."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

import httpx

from falcon_core.voice.faq_semantic import DEFAULT_THRESHOLD, FaqSemantic, ollama_embedder
from falcon_core.voice.textnorm import normalise

ROOT = Path(__file__).resolve().parents[4]
FIT = json.loads((ROOT / "evals/results/published/fits/voice_faq_threshold_fit.json").read_text("utf-8"))
DIM = 256


def vec(text: str) -> list[float]:
    v = [0.0] * DIM
    for w in normalise(text).split():
        v[int.from_bytes(hashlib.sha256(w.encode()).digest()[:2], "big") % DIM] += 1.0
    return v


class Fake:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.calls: list[int] = []
        self.delay, self.fail = delay, fail

    async def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(len(texts))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("down")
        return [vec(t) for t in texts]


QUESTIONS = {
    "otp": ("does the bank ask for my one time code", "هل البنك يطلب رمز التحقق"),
    "prize": ("i won a prize in a lottery",),
}


async def warmed(fake: Fake, **kw: float) -> FaqSemantic:
    sem = FaqSemantic(fake, questions=QUESTIONS, **kw)  # type: ignore[arg-type]
    assert await sem.warm()
    return sem


async def test_nearest_question_above_threshold_matches() -> None:
    sem = await warmed(Fake(), threshold=0.5)
    assert await sem.match("does my bank ask for the one time code") == "otp"
    assert await sem.match("I won a lottery prize") == "prize"
    assert await sem.match("هل البنك يطلب رمز التحقق مني") == "otp"


async def test_below_threshold_or_unrelated_returns_none() -> None:
    sem = await warmed(Fake(), threshold=0.5)
    assert await sem.match("what is the weather tomorrow in dubai") is None
    assert await sem.match("") is None
    assert await sem.match("   ") is None


async def test_threshold_is_the_gate() -> None:
    text = "bank code"
    assert await (await warmed(Fake(), threshold=0.01)).match(text) == "otp"
    assert await (await warmed(Fake(), threshold=0.99)).match(text) is None


async def test_bank_is_embedded_once_and_cached() -> None:
    fake = Fake()
    sem = await warmed(fake, threshold=0.5)
    await sem.match("i won a prize")
    await sem.match("i won a prize again")
    assert fake.calls == [3, 1, 1]  # the three bank questions once, then one call per utterance
    assert await sem.warm() and fake.calls == [3, 1, 1]


async def test_timeout_falls_back_to_none() -> None:
    sem = await warmed(Fake(), threshold=0.5)
    sem.embedder = Fake(delay=0.5)
    sem.timeout_s = 0.05
    assert await sem.match("i won a prize") is None


async def test_unreachable_model_never_raises_and_returns_none() -> None:
    sem = FaqSemantic(Fake(fail=True), questions=QUESTIONS, threshold=0.5)  # type: ignore[arg-type]
    assert not await sem.warm()
    assert await sem.match("i won a prize") is None
    await asyncio.sleep(0)  # the background warm attempt fails quietly
    assert not sem.ready


async def test_first_call_does_not_wait_for_the_bank() -> None:
    fake = Fake(delay=0.2)
    sem = FaqSemantic(fake, questions=QUESTIONS, threshold=0.5)  # type: ignore[arg-type]
    assert await sem.match("i won a prize") is None  # not warm yet: skipped at once, warming started
    await asyncio.sleep(0.4)
    assert sem.ready
    assert await sem.match("i won a prize") == "prize"


async def test_ollama_embedder_posts_model_and_parses_reply() -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["body"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0], [0.0, 1.0]]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    out = await ollama_embedder("http://ollama.test:11434/", client=client)(["a", "b"])
    assert out == [[1.0, 0.0], [0.0, 1.0]]
    assert seen["url"] == "http://ollama.test:11434/api/embed"
    assert seen["body"] == {"model": "qwen3-embedding:4b", "input": ["a", "b"], "keep_alive": "24h"}


async def test_ollama_embedder_rejects_a_short_reply() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={"embeddings": [[1]]}))
    )
    sem = FaqSemantic(ollama_embedder("http://x", client=client), questions=QUESTIONS, threshold=0.5)  # type: ignore[arg-type]
    assert not await sem.warm()


def test_threshold_is_the_fitted_one_and_the_fit_is_sound() -> None:
    assert FIT["chosen"]["threshold"] == DEFAULT_THRESHOLD
    assert FIT["model"] == "qwen3-embedding:4b"
    assert FIT["n_paraphrases"] >= 40
    assert FIT["chosen"]["offtopic_false_positive_rate"] == 0.0
    assert FIT["chosen"]["wrong_answer_rate"] == 0.0
    assert FIT["rules_then_embedding_recall"] >= FIT["keyword_rules_alone_recall"]
    assert "synthetic" in FIT["label"]
