"""Falcon Lens native voice STT. Runs on the Mac (Metal GPU) through mlx-whisper, never in Docker.

    POST /stt?lang=ar|en   body: audio bytes (webm/opus, ogg, wav, or raw PCM16 16 kHz with
                           Content-Type audio/L16)  ->  {text, lang, ms, duration_ms, model}
    GET  /healthz          always 200 once the process is up
    GET  /readyz           200 when the model is warm

Audio is decoded through ffmpeg pipes and numpy arrays only: nothing is written to disk. Transcripts
are never logged. Structure and the per-language prompt / repetition-guard lessons are adapted from
the owner's Neo project (an English prompt broke Arabic wake phrases, so each language has its own).

    cd services/voice-native && uv run uvicorn falcon_voice_native:app --host 127.0.0.1 --port 8093
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# The guards are shared with the API (packages/falcon_core); no install needed for this standalone project.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "falcon_core" / "src"))
from falcon_core.voice.guard import (  # noqa: E402
    FRAME_S,
    PROMPTS,
    clean_transcript,
    frame_stats,
    sniff,
    speech_like,
)

SAMPLE_RATE = 16000
MAX_AUDIO_S = 15.0
MAX_BYTES = 1024 * 1024
HF_REPO = "mlx-community/whisper-large-v3-turbo"
MODEL_NAME = "whisper-large-v3-turbo"
# The decoding prompt is per language (Neo lesson) and shared with the container engine: falcon_core.voice.guard.
# Optional speed knob (default off, decoding unchanged): skip Whisper's timestamp tokens (scripts/voice_stt_bench.py).
NO_TIMESTAMPS = os.environ.get("FL_WHISPER_NO_TIMESTAMPS", "") == "1"
TOKENS_PER_WORD = 6
SAMPLE_LEN_MAX = 224


def model_path() -> str:
    env = os.environ.get("FL_WHISPER_PATH", "").strip()
    if env:
        return str(Path(env).expanduser())
    shared = Path.home() / "neo-models" / MODEL_NAME
    return str(shared) if shared.is_dir() else HF_REPO


WHISPER = model_path()
TOKEN = os.environ.get("FL_VOICE_TOKEN", "")
log = logging.getLogger("falcon.voice.native")
logging.basicConfig(level=logging.INFO, format="%(message)s")
_lock = threading.Lock()  # one GPU job at a time
_state: dict[str, Any] = {"ready": False}


DEMUXERS = {"wav": "wav", "ogg": "ogg", "webm": "matroska,webm"}


def decode(raw: bytes, content_type: str) -> np.ndarray:
    """Audio bytes -> mono float32 16 kHz, in memory (ffmpeg pipes).

    The demuxer is forced from the content type and must agree with the magic bytes, so ffmpeg never probes
    (no concat/playlist/HLS/DASH demuxers). Protocols are limited to the pipe, output is capped at 15.5 s and
    there is no shell and a hard timeout.
    """
    if content_type.startswith("audio/l16"):
        return np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    family = content_type.split(";")[0].strip().removeprefix("audio/").removeprefix("x-")
    if family not in DEMUXERS or sniff(raw) != family:
        raise ValueError("unsupported audio container")
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-protocol_whitelist", "pipe",
        "-f", DEMUXERS[family], "-i", "pipe:0",
        "-t", str(MAX_AUDIO_S + 0.5),
        "-vn", "-sn", "-dn",
        "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1",
    ]  # fmt: skip
    r = subprocess.run(cmd, input=raw, capture_output=True, timeout=20, check=True)  # noqa: S603
    return np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768.0


def frame_rms(audio: np.ndarray) -> list[float]:
    """RMS of each 20 ms frame (input of the shared silence/noise gate)."""
    n = int(SAMPLE_RATE * FRAME_S)
    frames = audio[: len(audio) // n * n].reshape(-1, n)
    return [float(v) for v in np.sqrt((frames**2).mean(axis=1))] if len(frames) else []


def pick_lang(top: str | None, prob: float, hint: str | None) -> str:
    """Detector wins when it says ar/en with p >= 0.5; the hint only breaks ties (never forces); else Arabic."""
    if top in ("ar", "en") and prob >= 0.5:
        return str(top)
    return hint if hint in ("ar", "en") else "ar"


def detect_lang(audio: np.ndarray, hint: str | None = None) -> str:
    """Whisper language ID on the mel, resolved with pick_lang. Hold _lock."""
    import mlx.core as mx
    from mlx_whisper.audio import N_FRAMES, log_mel_spectrogram, pad_or_trim
    from mlx_whisper.transcribe import ModelHolder

    model = ModelHolder.get_model(WHISPER, mx.float16)
    mel = log_mel_spectrogram(audio, n_mels=model.dims.n_mels)
    _, probs = model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
    if not probs:
        return pick_lang(None, 0.0, hint)
    top = max(probs, key=lambda k: probs[k])
    return pick_lang(top, float(probs[top]), hint)


def transcribe(audio: np.ndarray, lang: str | None, voiced_s: float | None = None) -> tuple[str, str]:
    import mlx_whisper

    seconds = len(audio) / SAMPLE_RATE
    cap_words = max(8, int(seconds * 4.5) + 1)
    with _lock:
        language = detect_lang(audio, lang)
        r = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=WHISPER,
            language=language,
            initial_prompt=PROMPTS[language],
            condition_on_previous_text=False,
            no_speech_threshold=0.5,
            temperature=0.0,
            sample_len=min(SAMPLE_LEN_MAX, cap_words * TOKENS_PER_WORD),
            **({"without_timestamps": True} if NO_TIMESTAMPS else {}),
        )
    text = clean_transcript(str(r.get("text") or ""), seconds, r.get("segments") or [], voiced_s)
    return text, str(r.get("language") or language)


def warm() -> None:
    import mlx_whisper

    with _lock:
        mlx_whisper.transcribe(
            np.zeros(SAMPLE_RATE, dtype=np.float32), path_or_hf_repo=WHISPER, language="en"
        )  # downloads the HF model on first run when no local weights exist
    _state["ready"] = True
    log.info(json.dumps({"event": "warm", "model": MODEL_NAME}))


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(warm)  # model warm before the first request
    yield


app = FastAPI(title="falcon-voice-native", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def bearer(request: Request, call_next: Any) -> Any:
    if request.url.path not in ("/healthz", "/readyz"):
        if not TOKEN:  # fail closed: no shared secret configured, no speech recognition
            log.error(json.dumps({"event": "no_token", "reason": "FL_VOICE_TOKEN not configured"}))
            return JSONResponse({"error": "token_not_configured"}, status_code=503)
        sent = request.headers.get("authorization", "")
        if not hmac.compare_digest(sent.encode(), f"Bearer {TOKEN}".encode()):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "voice-native"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    ok = bool(_state["ready"])
    return JSONResponse({"status": "ready" if ok else "not_ready", "model_loaded": ok}, status_code=200 if ok else 503)


@app.post("/stt")
async def stt(request: Request, lang: str | None = None) -> JSONResponse:
    raw = await request.body()
    if not raw:
        return JSONResponse({"error": "empty"}, status_code=422)
    if len(raw) > MAX_BYTES:
        return JSONResponse({"error": "too_large"}, status_code=413)
    try:
        audio = await asyncio.to_thread(decode, raw, request.headers.get("content-type", "").lower())
    except (subprocess.SubprocessError, OSError, ValueError):
        return JSONResponse({"error": "undecodable"}, status_code=422)
    seconds = len(audio) / SAMPLE_RATE
    if seconds > MAX_AUDIO_S:
        return JSONResponse({"error": "too_long"}, status_code=422)
    if seconds < 0.1:
        return JSONResponse(
            {"text": "", "lang": None, "ms": 0, "duration_ms": round(seconds * 1000), "model": MODEL_NAME}
        )
    energies = frame_rms(audio)
    if not speech_like(energies):
        # Silence or flat noise: Whisper would echo its prompt (a false wake). Answer empty without running it.
        log.info(json.dumps({"event": "stt", "ms": 0, "audio_ms": round(seconds * 1000), "gate": "no_speech"}))
        return JSONResponse(
            {"text": "", "lang": None, "ms": 0, "duration_ms": round(seconds * 1000), "model": MODEL_NAME}
        )
    t0 = time.perf_counter()
    text, language = await asyncio.to_thread(
        transcribe, audio, lang if lang in ("ar", "en") else None, frame_stats(energies)[2]
    )
    ms = round((time.perf_counter() - t0) * 1000)
    log.info(json.dumps({"event": "stt", "ms": ms, "audio_ms": round(seconds * 1000), "lang": language}))  # no text
    return JSONResponse(
        {"text": text, "lang": language, "ms": ms, "duration_ms": round(seconds * 1000), "model": MODEL_NAME}
    )
