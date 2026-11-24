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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from falcon_core.contracts.voice import SttResult
from falcon_core.service import create_app
from falcon_core.voice.guard import clean_transcript

log = logging.getLogger("falcon.voice")

MAX_AUDIO_S = 15.0
MAX_BYTES = 1024 * 1024
TRANSCRIBE_TIMEOUT_S = 25.0
SAMPLE_RATE = 16000
# Short bias towards the product name. Per language: a mixed prompt makes Whisper echo it on noise.
PROMPTS = {"en": "Hey Falcon. Falcon Lens.", "ar": "يا فالكون. عدسة الصقر."}


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
                from faster_whisper import WhisperModel

                self.model = WhisperModel(
                    self.name,
                    device="cpu",
                    compute_type=self.compute,
                    cpu_threads=self.threads,
                    download_root=self.model_dir,
                    local_files_only=self.offline,
                )
                self.error = None
                log.info("whisper model loaded", extra={"model": self.name})
            except Exception as exc:  # noqa: BLE001 - download/IO errors are open-ended; log the class only
                self.error = type(exc).__name__
                log.warning("whisper model load failed", extra={"reason": self.error})

    def load_in_background(self) -> None:
        threading.Thread(target=self.load, name="whisper-load", daemon=True).start()

    def transcribe(self, raw: bytes, lang: str | None) -> SttResult:
        from faster_whisper.audio import decode_audio

        audio = decode_audio(io.BytesIO(raw), sampling_rate=SAMPLE_RATE)
        seconds = len(audio) / SAMPLE_RATE
        if seconds > MAX_AUDIO_S:
            raise AudioTooLongError(seconds)
        if self.model is None:
            self.load()
        if self.model is None:
            raise ModelUnavailableError(self.error or "loading")
        t0 = time.perf_counter()
        with self._lock:
            segments, info = self.model.transcribe(
                audio,
                language=lang,
                initial_prompt=PROMPTS.get(lang or "", PROMPTS["en"]) if lang else None,
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
            lang=str(info.language) if info.language else lang,
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
