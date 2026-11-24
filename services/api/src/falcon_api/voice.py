"""POST /v1/voice/utterance: "Hey Falcon" voice assistant (speech to wake phrase and intent).

Audio is validated, sent to a local STT engine (native Mac engine first, container fallback) and dropped.
It is never written to disk, never logged. Transcripts are returned to the caller and nowhere else: not
in logs, not in metric labels, not in the audit log. Wake phrase and intent are deterministic (no LLM).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, Form, Request, Response, UploadFile
from opentelemetry import trace
from prometheus_client import CollectorRegistry, Counter, Histogram

from falcon_api.auth import Principal
from falcon_api.problem import PROBLEM_RESPONSES, Problem
from falcon_core.contracts.voice import SttResult, VoiceUtterance
from falcon_core.telemetry.tracing import fl_span, set_span_attrs, traceparent_of
from falcon_core.voice.intent import analyse

log = logging.getLogger("falcon.api.voice")

MAX_AUDIO_BYTES = 1024 * 1024
MAX_AUDIO_S = 15.0
ALLOWED_TYPES = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/vnd.wave": "wav",
}
DEFAULT_STT_URLS = "http://host.docker.internal:8093,http://voice:8000"
HEALTH_TTL_S = 10.0
LOCAL_HOSTS = {"host.docker.internal", "localhost", "127.0.0.1"}


def sniff(data: bytes) -> str | None:
    """Container family from magic bytes: wav (RIFF/WAVE), ogg (OggS), webm (EBML header)."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def wav_seconds(data: bytes) -> float | None:
    """Length of a canonical PCM wav from its header (None when it cannot be read cheaply)."""
    if len(data) < 44 or data[:4] != b"RIFF":
        return None
    pos = 12
    byte_rate = 0
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], int.from_bytes(data[pos + 4 : pos + 8], "little")
        if cid == b"fmt " and pos + 20 <= len(data):
            byte_rate = int.from_bytes(data[pos + 16 : pos + 20], "little")
        if cid == b"data":
            size = min(size, len(data) - pos - 8) if size == 0xFFFFFFFF else size
            return size / byte_rate if byte_rate else None
        pos += 8 + size + (size & 1)
    return None


class SttEngine:
    def __init__(self, name: str, url: str) -> None:
        self.name, self.url = name, url.rstrip("/")
        self.down_until = 0.0

    @property
    def usable(self) -> bool:
        return time.monotonic() >= self.down_until


def parse_engines(spec: str) -> list[SttEngine]:
    """`name=url,name=url` or bare urls (host.docker.internal / localhost = native, anything else = container)."""
    engines: list[SttEngine] = []
    for raw in (p.strip() for p in spec.split(",")):
        if not raw:
            continue
        name, _, url = raw.partition("=") if "=" in raw.split("://", 1)[0] else ("", "", raw)
        if not name:
            name = "native" if (urlsplit(url).hostname or "") in LOCAL_HOSTS else "container"
        engines.append(SttEngine(name, url))
    return engines


class SttUnavailableError(Exception):
    pass


class SttRejectedError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


class SttRouter:
    """Ordered engines: the first healthy one answers; a connection failure or 5xx parks it for HEALTH_TTL_S."""

    def __init__(self, engines: list[SttEngine], token: str, client: httpx.AsyncClient | None = None) -> None:
        self.engines = engines
        self.token = token
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=1.5))

    async def transcribe(self, audio: bytes, content_type: str, lang: str | None) -> tuple[str, SttResult]:
        headers = {"Content-Type": content_type}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        params = {"lang": lang} if lang else {}
        for eng in self.engines:
            if not eng.usable:
                continue
            try:
                r = await self.client.post(f"{eng.url}/stt", content=audio, headers=headers, params=params)
            except httpx.HTTPError:
                eng.down_until = time.monotonic() + HEALTH_TTL_S
                continue
            if r.status_code in (413, 422):
                raise SttRejectedError(
                    r.status_code, str(r.json().get("error", "rejected")) if r.content else "rejected"
                )
            if r.status_code != 200:  # 503 model loading, 504 timeout, 401 misconfigured: try the next engine
                eng.down_until = time.monotonic() + (2.0 if r.status_code == 503 else HEALTH_TTL_S)
                continue
            return eng.name, SttResult.model_validate(r.json())
        raise SttUnavailableError

    async def aclose(self) -> None:
        await self.client.aclose()


def register(
    app: FastAPI,
    *,
    require: Callable[[str], Callable[..., Awaitable[Principal]]],
    count: Callable[[str], Awaitable[int]],
    client_ip: Callable[[Request], str],
    registry: CollectorRegistry,
    router_factory: Callable[[], SttRouter] | None = None,
) -> None:
    utterances = Counter(
        "fl_voice_utterances_total", "Voice utterances handled", ["wake", "intent", "lang", "engine"], registry=registry
    )
    latency = Histogram(
        "fl_voice_latency_seconds",
        "Time from upload to answer (STT included)",
        ["engine"],
        buckets=(0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 25),
        registry=registry,
    )
    errors = Counter("fl_voice_errors_total", "Voice request failures", ["reason"], registry=registry)
    per_min = int(os.environ.get("FL_VOICE_RATE_PER_MIN", "30"))
    holder: dict[str, SttRouter] = {}

    def stt_router() -> SttRouter:
        if "r" not in holder:
            holder["r"] = (
                router_factory()
                if router_factory
                else SttRouter(
                    parse_engines(os.environ.get("FL_VOICE_STT_URLS", DEFAULT_STT_URLS)),
                    os.environ.get("FL_VOICE_TOKEN", ""),
                )
            )
        return holder["r"]

    def fail(status: int, slug: str, title: str, reason: str, headers: dict[str, str] | None = None) -> Problem:
        errors.labels(reason).inc()
        return Problem(status, slug, title, headers=headers)

    responses: dict[int | str, dict[str, Any]] = {
        **PROBLEM_RESPONSES,
        200: {"model": VoiceUtterance, "description": "Transcript, wake flag and intent."},
    }

    @app.post(
        "/v1/voice/utterance",
        tags=["voice"],
        response_model=VoiceUtterance,
        responses=responses,
        summary="Transcribe one spoken utterance and read its wake phrase and intent",
        dependencies=[Depends(require("read"))],
    )
    async def utterance(
        request: Request,
        response: Response,
        audio: Annotated[
            UploadFile, File(description="audio/webm;codecs=opus, audio/wav or audio/ogg; max 15 s and 1 MB")
        ],
        lang_hint: Annotated[str | None, Form(description="ar or en (optional)")] = None,
    ) -> VoiceUtterance:
        # One span per utterance (engine, lang, wake, intent, duration: never the transcript or audio). Its W3C
        # `traceparent` goes back in a response header so the checks this utterance starts can be linked to it.
        with fl_span("voice.utterance", "CHAIN") as span:
            out = await handle_utterance(request, audio, lang_hint, span)
            tp = traceparent_of(span)
            if tp:
                response.headers["traceparent"] = tp
            return out

    async def handle_utterance(
        request: Request, audio: UploadFile, lang_hint: str | None, span: trace.Span
    ) -> VoiceUtterance:
        t0 = time.perf_counter()
        bucket = f"rl:voice:{client_ip(request)}:{int(time.time() // 60)}"
        if per_min > 0 and await count(bucket) > per_min:
            raise fail(
                429,
                "rate-limited",
                "Rate limit exceeded",
                "rate_limited",
                {"Retry-After": str(60 - int(time.time() % 60)), "X-RateLimit-Limit": str(per_min)},
            )
        if lang_hint is not None and lang_hint not in ("ar", "en"):
            raise fail(422, "invalid-lang-hint", "lang_hint must be ar or en", "bad_lang_hint")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise fail(413, "payload-too-large", "Audio larger than 1 MB", "too_large")
        if not data:
            raise fail(422, "empty-audio", "Empty audio", "empty")
        declared = (audio.content_type or "").split(";")[0].strip().lower()
        family = ALLOWED_TYPES.get(declared)
        if family is None or sniff(data) != family:
            raise fail(415, "unsupported-media-type", "Expected audio/webm (opus), audio/wav or audio/ogg", "bad_type")
        secs = wav_seconds(data) if family == "wav" else None
        if secs is not None and secs > MAX_AUDIO_S:
            raise fail(422, "audio-too-long", "Audio longer than 15 seconds", "too_long")
        try:
            engine, res = await stt_router().transcribe(data, f"audio/{family}", lang_hint)
        except SttRejectedError as exc:
            if exc.status == 413:
                raise fail(413, "payload-too-large", "Audio larger than 1 MB", "too_large") from exc
            slug, title = (
                ("audio-too-long", "Audio longer than 15 seconds")
                if exc.reason == "too_long"
                else ("undecodable-audio", "Audio could not be decoded")
            )
            raise fail(422, slug, title, "too_long" if exc.reason == "too_long" else "undecodable") from exc
        except SttUnavailableError as exc:
            raise fail(503, "stt-unavailable", "Speech recognition unavailable", "stt_unavailable") from exc
        transcript = res.text.strip()[:300]
        result = analyse(transcript)
        lang = res.lang if res.lang in ("ar", "en") else "other"
        elapsed = time.perf_counter() - t0
        utterances.labels(str(result.wake).lower(), result.intent, lang, engine).inc()
        latency.labels(engine).observe(elapsed)
        attrs: dict[str, str | int | bool] = {
            "fl.voice.engine": engine,
            "fl.voice.lang": lang,
            "fl.voice.wake": result.wake,
            "fl.voice.intent": result.intent,
            "fl.voice.duration_ms": round(elapsed * 1000),
        }
        set_span_attrs(span, **attrs)
        # No transcript, no audio: engine, timing and the intent code only.
        log.info(
            "voice utterance",
            extra={"engine": engine, "intent": result.intent, "wake": result.wake, "latency_ms": round(elapsed * 1000)},
        )
        return VoiceUtterance(
            transcript=transcript,
            lang=lang,
            wake=result.wake,
            intent=result.intent,
            command=result.command[:300],
            duration_ms=res.duration_ms,
            model=f"{engine}:{res.model}",
        )
