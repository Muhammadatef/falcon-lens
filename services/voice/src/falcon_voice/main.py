"""Falcon Lens voice STT container entrypoint.

What it does:
    Serves POST /stt (faster-whisper, CPU) plus /healthz /readyz /metrics on port 8000.
When to use it:
    The `voice` container starts it; it is the fallback when the native Mac engine is not running.
How to run:
    make up   (direct: uv run python -m falcon_voice.main)
Inputs:
    FL_WHISPER_MODEL (default small), FL_WHISPER_COMPUTE (int8), FL_VOICE_MODEL_DIR (/models),
    FL_VOICE_TOKEN (bearer), FL_VOICE_PRELOAD (true), FL_VOICE_OFFLINE (false).
Outputs / side effects:
    Downloads the model once into FL_VOICE_MODEL_DIR. Writes nothing else; audio and text are never stored.
"""

from __future__ import annotations

from falcon_core.service import run
from falcon_voice.app import build_app

app = build_app()

if __name__ == "__main__":
    run(app)
