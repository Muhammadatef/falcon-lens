"""Native STT service (no mlx needed: the model is only touched by warm() and transcribe())."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    monkeypatch.setenv("FL_VOICE_TOKEN", "t0ken")
    monkeypatch.setenv("FL_WHISPER_PATH", "/nonexistent/whisper")
    sys.modules.pop("falcon_voice_native", None)
    return importlib.import_module("falcon_voice_native")


def test_model_path_prefers_env_then_shared_then_hf(mod, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    assert mod.model_path() == "/nonexistent/whisper"
    monkeypatch.delenv("FL_WHISPER_PATH")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert mod.model_path() == mod.HF_REPO
    (tmp_path / "neo-models" / mod.MODEL_NAME).mkdir(parents=True)
    assert mod.model_path() == str(tmp_path / "neo-models" / mod.MODEL_NAME)


def test_pcm16_decode_is_in_memory(mod) -> None:  # type: ignore[no-untyped-def]
    pcm = (np.ones(1600, dtype="<i2") * 16384).tobytes()
    audio = mod.decode(pcm, "audio/l16")
    assert audio.dtype == np.float32
    assert abs(float(audio[0]) - 0.5) < 1e-3


def test_http_surface(mod) -> None:  # type: ignore[no-untyped-def]
    c = TestClient(mod.app)  # no lifespan: model never loads
    assert c.get("/healthz").status_code == 200
    assert c.get("/readyz").status_code == 503
    assert c.post("/stt", content=b"x").status_code == 401
    h = {"Authorization": "Bearer t0ken"}
    assert c.post("/stt", content=b"", headers=h).status_code == 422
    assert c.post("/stt", content=b"\x00" * (1024 * 1024 + 1), headers=h).status_code == 413
    assert c.post("/stt", content=b"not audio at all", headers={**h, "Content-Type": "audio/wav"}).status_code == 422
    too_long = (np.zeros(16000 * 16, dtype="<i2")).tobytes()  # 16 s of raw PCM, 512 KB
    assert c.post("/stt", content=too_long, headers={**h, "Content-Type": "audio/L16"}).status_code == 422


def test_pick_lang_hint_only_breaks_ties(mod) -> None:  # type: ignore[no-untyped-def]
    assert mod.pick_lang("ar", 0.9, "en") == "ar"
    assert mod.pick_lang("en", 0.9, "ar") == "en"
    assert mod.pick_lang("fr", 0.3, "en") == "en"
    assert mod.pick_lang("en", 0.3, None) == "ar"
