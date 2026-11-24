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
import time
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
#: How long Ollama keeps the embedding model in memory after a call. Its default is minutes (measured here: the
#: model was unloaded 2 minutes after the last call and the next call took 6.1 s to load it, against 0.13-0.18 s
#: warm), so a question asked after a pause would always miss the 0.4 s budget. FL_VOICE_EMBED_KEEP_ALIVE overrides.
DEFAULT_KEEP_ALIVE = "24h"
#: A background ping at most this often keeps the model loaded and reloads it if Ollama evicted it.
KEEP_WARM_EVERY_S = 60.0
Outcome = str  # "hit" | "miss" | "warming" | "timeout" | "error"


def ollama_embedder(
    base_url: str | None = None,
    model: str | None = None,
    client: httpx.AsyncClient | None = None,
    keep_alive: str | None = None,
) -> Embedder:
    """POST {base}/api/embed {model, input: [...], keep_alive} -> {embeddings: [[...]]} (Ollama, local).

    One HTTP client is kept for the life of the process (no new connection per utterance).
    """
    base = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://host.docker.internal:11434").rstrip("/")
    name = model or os.environ.get("FL_VOICE_EMBED_MODEL") or DEFAULT_MODEL
    keep = keep_alive or os.environ.get("FL_VOICE_EMBED_KEEP_ALIVE") or DEFAULT_KEEP_ALIVE
    holder: dict[str, httpx.AsyncClient] = {}

    async def embed(texts: Sequence[str]) -> list[list[float]]:
        c = client or holder.get("c")
        if c is None:
            c = holder["c"] = httpx.AsyncClient(timeout=httpx.Timeout(WARM_TIMEOUT_S, connect=2.0))
        r = await c.post(f"{base}/api/embed", json={"model": name, "input": list(texts), "keep_alive": keep})
        r.raise_for_status()
        data: Any = r.json()
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
        self._ping: asyncio.Task[None] | None = None
        self._last_ok = 0.0

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
        self._last_ok = time.monotonic()
        return True

    def start_warming(self) -> None:
        """Kick off `warm()` in the background (idempotent); utterances before it finishes just skip the fallback."""
        if self._bank or (self._warming and not self._warming.done()):
            return
        self._warming = asyncio.get_running_loop().create_task(self.warm())

    def keep_warm(self, *, force: bool = False) -> None:
        """Background ping (at most every KEEP_WARM_EVERY_S, or now with `force`) so the model stays loaded.

        Called at the start of every utterance, while speech recognition runs: if Ollama unloaded the model, the
        reload happens here and not inside a user's 0.4 s budget. Never raises, never blocks.
        """
        if not self._bank:
            self.start_warming()
            return
        if self._ping and not self._ping.done():
            return
        if not force and time.monotonic() - self._last_ok < KEEP_WARM_EVERY_S:
            return

        async def ping() -> None:
            try:
                await asyncio.wait_for(self.embedder(["ping"]), WARM_TIMEOUT_S)
                self._last_ok = time.monotonic()
            except Exception:  # noqa: S110 - best effort; the keyword rules still answer
                pass

        self._ping = asyncio.get_running_loop().create_task(ping())

    async def scores(self, text: str) -> list[tuple[str, float]]:
        """Best cosine per FAQ name, highest first. Raises on failure or timeout (callers use `match`)."""
        if not self._bank and not await self.warm():
            raise RuntimeError("faq embeddings unavailable")
        (vec,) = await asyncio.wait_for(self.embedder([text]), self.timeout_s)
        self._last_ok = time.monotonic()
        q = _unit(vec)
        best: dict[str, float] = {}
        for name, v in self._bank:
            best[name] = max(best.get(name, -1.0), cosine(q, v))
        return sorted(best.items(), key=lambda kv: -kv[1])

    async def match_outcome(self, text: str) -> tuple[str | None, Outcome]:
        """(FAQ name or None, why): hit, miss (below threshold), warming, timeout or error. Never raises."""
        if not text.strip():
            return None, "miss"
        if not self._bank:
            self.start_warming()  # first calls only; do not make the user wait for the whole bank
            return None, "warming"
        try:
            ranked = await self.scores(text)
        except TimeoutError:
            self.keep_warm(force=True)  # the model was probably unloaded: reload it in the background for next time
            return None, "timeout"
        except Exception:
            return None, "error"
        name, score = ranked[0]
        return (name, "hit") if score >= self.threshold else (None, "miss")

    async def match(self, text: str) -> str | None:
        """FAQ name when the nearest question is at least `threshold` similar, else None. Never raises."""
        return (await self.match_outcome(text))[0]
