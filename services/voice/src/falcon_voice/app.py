"""Falcon Lens voice STT, container fallback: faster-whisper on CPU.

POST /stt  body = raw audio bytes (webm/opus, ogg, wav), optional ?lang=ar|en  ->  {text, lang, ms, duration_ms, model}

Audio is decoded in memory and dropped; transcripts are never logged or put in metrics. The model is
downloaded lazily into FL_VOICE_MODEL_DIR (a named volume) in a background thread, so the service is
healthy (/healthz) immediately and /readyz reports ``model_loaded``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from falcon_core.contracts.voice import SttResult
from falcon_core.service import create_app
from falcon_core.voice.guard import clean_transcript, sniff

log = logging.getLogger("falcon.voice")

MAX_AUDIO_S = 15.0
MAX_BYTES = 1024 * 1024
TRANSCRIBE_TIMEOUT_S = 25.0
SAMPLE_RATE = 16000
# Short bias towards the product name. Per language: a mixed prompt makes Whisper echo it on noise.
PROMPTS = {"en": "Hey Falcon. Falcon Lens.", "ar": "يا صقر. عدسة الصقر."}


MIN_LANG_PROB = 0.5


def choose_lang(detected: str | None, prob: float, hint: str | None) -> str:
    """Per-utterance language: the detector wins when it is sure and says ar/en. The hint only breaks ties
    (never forces); with neither, Arabic (the product is Arabic-first)."""
    if detected in ("ar", "en") and prob >= MIN_LANG_PROB:
        return str(detected)
    return hint if hint in ("ar", "en") else "ar"


FORMATS = {"wav": "wav", "ogg": "ogg", "webm": "matroska,webm", "mp4": "mov,mp4,m4a,3gp,3g2,mj2", "aac": "aac"}


def decode(raw: bytes) -> np.ndarray:
    """Audio bytes -> mono float32 16 kHz, in memory.

    The demuxer is forced from the magic bytes (wav, ogg, webm only), so libav never probes: concat, HLS and
    DASH playlists and anything else are refused. Decoding stops past MAX_AUDIO_S, which bounds memory.
    """
    import av

    family = sniff(raw)
    if family is None:
        raise ValueError("unsupported audio container")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    total = 0
    with av.open(
        io.BytesIO(raw), mode="r", format=FORMATS[family], options={"protocol_whitelist": "pipe"}
    ) as container:
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                arr = out.to_ndarray().reshape(-1)
                chunks.append(arr)
                total += len(arr)
            if total > (MAX_AUDIO_S + 0.5) * SAMPLE_RATE:
                break
    pcm = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


class Engine:
    """Lazy faster-whisper model holder. One transcription at a time (CPU bound)."""

    def __init__(self) -> None:
        self.name = os.environ.get("FL_WHISPER_MODEL", "small")
        self.model_dir = os.environ.get("FL_VOICE_MODEL_DIR", "/models")
        self.compute = os.environ.get("FL_WHISPER_COMPUTE", "int8")
        self.threads = int(os.environ.get("FL_WHISPER_THREADS", "4"))
        self.offline = os.environ.get("FL_VOICE_OFFLINE", "false").lower() == "true"
        self.model: Any = None
        self.error: str | None = None
        self._lock = threading.Lock()
        self._loading = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def load(self) -> None:
        with self._loading:
            if self.model is not None:
                return
            try:
                self.model = self._open(local_only=True)  # present in the volume: no network, ever
            except Exception:  # noqa: BLE001 - not downloaded yet (LocalEntryNotFoundError and friends)
                if self.offline:
                    self.error = "model_missing_offline"
                    log.warning("whisper model missing and FL_VOICE_OFFLINE=true", extra={"reason": self.error})
                    return
                try:
                    self.model = self._open(local_only=False)  # one-time download through the egress proxy
                except Exception as exc:  # noqa: BLE001 - download/IO errors are open-ended; log the class only
                    self.error = type(exc).__name__
                    log.warning("whisper model load failed", extra={"reason": self.error})
                    return
            self.error = None
            log.info("whisper model loaded", extra={"model": self.name})

    def _open(self, *, local_only: bool) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.name,
            device="cpu",
            compute_type=self.compute,
            cpu_threads=self.threads,
            download_root=self.model_dir,
            local_files_only=local_only,
        )

    def load_in_background(self) -> None:
        threading.Thread(target=self.load, name="whisper-load", daemon=True).start()

    def _detect(self, audio: np.ndarray) -> tuple[str | None, float]:
        """Whisper language ID on this utterance (hold _lock). Never raises: unknown -> (None, 0)."""
        try:
            code, prob, _all = self.model.detect_language(audio)
            return (str(code) if code else None), float(prob)
        except Exception:  # noqa: BLE001 - detection is advisory; fall back to hint / Arabic
            return None, 0.0

    def transcribe(self, raw: bytes, lang: str | None) -> SttResult:
        audio = decode(raw)
        seconds = len(audio) / SAMPLE_RATE
        if seconds > MAX_AUDIO_S:
            raise AudioTooLongError(seconds)
        if self.model is None:
            self.load()
        if self.model is None:
            raise ModelUnavailableError(self.error or "loading")
        t0 = time.perf_counter()
        with self._lock:
            detected, prob = self._detect(audio)
            used = choose_lang(detected, prob, lang)
            segments, _info = self.model.transcribe(
                audio,
                language=used,
                initial_prompt=PROMPTS[used],
                beam_size=1,
                temperature=0.0,
                condition_on_previous_text=False,
                without_timestamps=True,
                no_speech_threshold=0.5,
            )
            segs = [{"text": s.text, "compression_ratio": s.compression_ratio} for s in segments]
        text = clean_transcript("".join(str(s["text"]) for s in segs), seconds, segs)
        return SttResult(
            text=text,
            lang=used,
            ms=round((time.perf_counter() - t0) * 1000),
            duration_ms=round(seconds * 1000),
            model=f"faster-whisper-{self.name}",
        )


class AudioTooLongError(Exception):
    def __init__(self, seconds: float) -> None:
        super().__init__("audio too long")
        self.seconds = seconds


class ModelUnavailableError(Exception):
    pass


def build_app(engine: Engine | None = None) -> FastAPI:
    eng = engine or Engine()

    async def model_loaded() -> bool:
        return eng.loaded

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if os.environ.get("FL_VOICE_PRELOAD", "true").lower() == "true":
            eng.load_in_background()  # never blocks startup or /healthz
        yield

    token = os.environ.get("FL_VOICE_TOKEN", "")
    if not token:  # fail closed: create_app answers 503 on every path except the health checks
        log.error("voice token not configured", extra={"reason": "no_token"})
    app = create_app("voice", deps={"model_loaded": model_loaded}, lifespan=lifespan, protect=True, token=token)

    @app.post("/stt")
    async def stt(request: Request, lang: str | None = None) -> JSONResponse:
        raw = await request.body()
        if not raw:
            return JSONResponse({"error": "empty"}, status_code=422)
        if len(raw) > MAX_BYTES:
            return JSONResponse({"error": "too_large"}, status_code=413)
        hint = lang if lang in ("ar", "en") else None
        try:
            result = await asyncio.wait_for(asyncio.to_thread(eng.transcribe, raw, hint), TRANSCRIBE_TIMEOUT_S)
        except AudioTooLongError:
            return JSONResponse({"error": "too_long"}, status_code=422)
        except ModelUnavailableError:
            return JSONResponse({"error": "model_unavailable"}, status_code=503)
        except TimeoutError:
            return JSONResponse({"error": "timeout"}, status_code=504)
        except Exception:  # noqa: BLE001 - undecodable audio: PyAV raises many types; never echo details
            return JSONResponse({"error": "undecodable"}, status_code=422)
        return JSONResponse(result.model_dump())

    return app
