"""Semantic FAQ fallback: cosine similarity between the spoken question and the FAQ questions, nothing generated.

Used only when no keyword rule fired. The embedding model (default `qwen3-embedding:4b` on the local Ollama) turns
text into numbers; the answer is still a pre-written clip chosen by nearest question. Any failure or a call slower
than `timeout_s` returns None, and the caller falls back to the off-topic redirect. The threshold comes from
evals/results/published/fits/voice_faq_threshold_fit.json (scripts/voice_faq_fit.py); the transcript is never logged.
"""

from __future__ import annotations

import asyncio
import math
import os
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from falcon_core.voice.faq_questions import QUESTIONS

Embedder = Callable[[Sequence[str]], Awaitable[list[list[float]]]]

DEFAULT_MODEL = "qwen3-embedding:4b"
#: Cosine threshold fitted on the labelled paraphrase set (see the fit artifact); a test pins it to the artifact.
DEFAULT_THRESHOLD = 0.68
#: Hard budget for embedding one utterance (the question bank is embedded once, in the background, at start).
DEFAULT_TIMEOUT_S = 0.4
WARM_TIMEOUT_S = 60.0


def ollama_embedder(
    base_url: str | None = None, model: str | None = None, client: httpx.AsyncClient | None = None
) -> Embedder:
    """POST {base}/api/embed {model, input: [...]} -> {embeddings: [[...]]} (Ollama, local)."""
    base = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434").rstrip("/")
    name = model or os.environ.get("FL_VOICE_EMBED_MODEL") or DEFAULT_MODEL

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        c = client or httpx.AsyncClient(timeout=httpx.Timeout(WARM_TIMEOUT_S, connect=2.0))
        try:
            r = await c.post(f"{base}/api/embed", json={"model": name, "input": list(texts)})
            r.raise_for_status()
            data: Any = r.json()
        finally:
            if client is None:
                await c.aclose()
        out = data["embeddings"]
        if len(out) != len(texts):
            raise ValueError("embedding count mismatch")
        return [[float(x) for x in v] for v in out]

    return embed


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


class FaqSemantic:
    """Nearest-question search over precomputed, unit-length FAQ question embeddings."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        questions: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.embedder = embedder
        self.threshold = threshold
        self.timeout_s = timeout_s
        self.questions = questions or QUESTIONS
        self._bank: list[tuple[str, list[float]]] = []
        self._warming: asyncio.Task[bool] | None = None

    @property
    def ready(self) -> bool:
        return bool(self._bank)

    async def warm(self) -> bool:
        """Embed the question bank once (cached for the life of the process). False when the model is unreachable."""
        if self._bank:
            return True
        names = [n for n, qs in self.questions.items() for _ in qs]
        texts = [q for qs in self.questions.values() for q in qs]
        try:
            vecs = await asyncio.wait_for(self.embedder(texts), WARM_TIMEOUT_S)
        except Exception:  # unreachable model, timeout, bad reply: the keyword rules still work
            return False
        self._bank = [(n, _unit(v)) for n, v in zip(names, vecs, strict=True)]
        return True

    def start_warming(self) -> None:
        """Kick off `warm()` in the background (idempotent); utterances before it finishes just skip the fallback."""
        if self._bank or (self._warming and not self._warming.done()):
            return
        self._warming = asyncio.get_running_loop().create_task(self.warm())

    async def scores(self, text: str) -> list[tuple[str, float]]:
        """Best cosine per FAQ name, highest first. Raises on failure or timeout (callers use `match`)."""
        if not self._bank and not await self.warm():
            raise RuntimeError("faq embeddings unavailable")
        (vec,) = await asyncio.wait_for(self.embedder([text]), self.timeout_s)
        q = _unit(vec)
        best: dict[str, float] = {}
        for name, v in self._bank:
            best[name] = max(best.get(name, -1.0), cosine(q, v))
        return sorted(best.items(), key=lambda kv: -kv[1])

    async def match(self, text: str) -> str | None:
        """FAQ name when the nearest question is at least `threshold` similar, else None. Never raises."""
        if not text.strip():
            return None
        if not self._bank:
            self.start_warming()  # first calls only; do not make the user wait for the whole bank
            return None
        try:
            ranked = await self.scores(text)
        except Exception:
            return None
        name, score = ranked[0]
        return name if score >= self.threshold else None
