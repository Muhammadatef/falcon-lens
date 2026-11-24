"""Container STT service: health independent of the model, readiness, caps, error mapping, privacy."""

from __future__ import annotations

import io
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from falcon_core.contracts.voice import SttResult
from falcon_voice import app as voice_app
from falcon_voice.app import AudioTooLongError, Engine, ModelUnavailableError, build_app

H = {"Authorization": "Bearer t0ken"}


class FakeEngine(Engine):
    def __init__(self, *, loaded: bool = False, raises: Exception | None = None) -> None:
        super().__init__()
        self.model = object() if loaded else None
        self.raises = raises
        self.loads = 0

    def load(self) -> None:  # never touches the network in tests
        self.loads += 1

    def transcribe(self, raw: bytes, lang: str | None) -> SttResult:
        if self.raises:
            raise self.raises
        return SttResult(
            text="hey falcon check", lang=lang or "en", ms=5, duration_ms=1000, model="faster-whisper-fake"
        )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_VOICE_TOKEN", "t0ken")
    monkeypatch.setenv("FL_VOICE_PRELOAD", "false")


def client(eng: Engine) -> TestClient:
    return TestClient(build_app(eng))


def test_healthz_does_not_depend_on_model() -> None:
    c = client(FakeEngine(loaded=False))
    assert c.get("/healthz").status_code == 200
    r = c.get("/readyz")
    assert r.status_code == 503
    assert r.json()["deps"]["model_loaded"] is False


def test_readyz_reports_model_loaded() -> None:
    r = client(FakeEngine(loaded=True)).get("/readyz")
    assert r.status_code == 200
    assert r.json()["deps"] == {"model_loaded": True}


def test_auth_required_for_stt_and_metrics() -> None:
    c = client(FakeEngine(loaded=True))
    assert c.post("/stt", content=b"x").status_code == 401
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers=H).status_code == 200


def test_stt_ok_and_caps() -> None:
    c = client(FakeEngine(loaded=True))
    r = c.post("/stt?lang=ar", content=b"audio", headers=H)
    assert r.status_code == 200
    assert r.json()["lang"] == "ar"
    assert c.post("/stt", content=b"", headers=H).status_code == 422
    assert c.post("/stt", content=b"\x00" * (1024 * 1024 + 1), headers=H).status_code == 413


@pytest.mark.parametrize(
    ("exc", "status"),
    [
        (AudioTooLongError(20.0), 422),
        (ModelUnavailableError("loading"), 503),
        (TimeoutError(), 504),
        (ValueError("x"), 422),
    ],
)
def test_error_mapping(exc: Exception, status: int) -> None:
    assert client(FakeEngine(loaded=True, raises=exc)).post("/stt", content=b"x", headers=H).status_code == status


def test_no_transcript_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client(FakeEngine(loaded=True)).post("/stt", content=b"x", headers=H)
    assert all("hey falcon" not in str(rec.__dict__) for rec in caplog.records)


def test_lazy_model_is_not_loaded_at_import_or_startup() -> None:
    eng = FakeEngine(loaded=False)
    with TestClient(build_app(eng)) as c:  # lifespan runs; PRELOAD=false
        assert c.get("/healthz").status_code == 200
    assert eng.loads == 0


def test_prompts_are_per_language() -> None:
    p: Any = voice_app.PROMPTS
    assert "صقر" in p["ar"]
    assert not any("؀" <= ch <= "ۿ" for ch in p["en"])


def _wav(seconds: float) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


def test_real_decoder_reads_wav_in_memory_and_enforces_duration() -> None:
    """Guards the faster-whisper / PyAV pairing (PyAV 19 broke decode_audio) without loading a model."""
    eng = Engine()
    eng.model = object()  # never reached for the long clip; short clip would call .transcribe on it
    with pytest.raises(AudioTooLongError):
        eng.transcribe(_wav(16), None)
    import io

    from faster_whisper.audio import decode_audio

    assert len(decode_audio(io.BytesIO(_wav(1)), sampling_rate=16000)) == 16000


class DetectModel:
    """Fake faster-whisper model: fixed language ID, records the language it transcribes with."""

    def __init__(self, code: str, prob: float) -> None:
        self.code, self.prob = code, prob
        self.used: list[tuple[str | None, str | None]] = []

    def detect_language(self, audio: Any) -> tuple[str, float, list[Any]]:
        return self.code, self.prob, []

    def transcribe(self, audio: Any, **kw: Any) -> tuple[list[Any], Any]:
        self.used.append((kw["language"], kw["initial_prompt"]))
        seg = type("S", (), {"text": "hey falcon", "compression_ratio": 1.0})()
        return [seg], type("I", (), {"language": kw["language"]})()


def _run(code: str, prob: float, hint: str | None) -> tuple[str | None, DetectModel]:
    eng = Engine()
    model = DetectModel(code, prob)
    eng.model = model
    res = eng.transcribe(_speech_wav(), hint)
    return res.lang, model


def _speech_wav(seconds: float = 1.5, noise: float = 0.0) -> bytes:
    """Speech-shaped audio: 140 ms tone bursts with 100 ms gaps (silent audio no longer reaches the model)."""
    import wave

    import numpy as np

    rate = 16000
    t = np.arange(int(rate * seconds)) / rate
    burst = ((t % 0.24) < 0.14).astype(np.float32)
    pcm = 0.3 * np.sin(2 * np.pi * 220 * t) * burst + noise * np.random.default_rng(7).standard_normal(len(t))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _steady_wav(seconds: float, level: float) -> bytes:
    import wave

    import numpy as np

    pcm = level * np.random.default_rng(3).standard_normal(int(16000 * seconds))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_silence_and_steady_noise_never_reach_the_model() -> None:
    """Measured on the live engine: silence came back as "Falcon Lens." and noise as a wake phrase (prompt echo)."""
    for clip in (_wav(3), _steady_wav(3, 0.01), _steady_wav(3, 0.2)):
        eng = Engine()
        model = DetectModel("en", 0.9)
        eng.model = model
        res = eng.transcribe(clip, None)
        assert (res.text, res.lang, res.ms) == ("", None, 0)
        assert model.used == []  # Whisper was not run at all


def test_speech_in_a_noisy_room_reaches_the_model() -> None:
    eng = Engine()
    model = DetectModel("en", 0.9)
    eng.model = model
    res = eng.transcribe(_speech_wav(noise=0.03), None)
    assert res.text == "hey falcon"
    assert len(model.used) == 1


def test_two_words_over_seconds_of_continuous_sound_are_dropped() -> None:
    """Modulated noise passes the level gate; a 2-word transcript out of 4 s of unbroken sound is still an echo."""
    import wave

    import numpy as np

    t = np.arange(16000 * 4) / 16000
    pcm = 0.05 * np.random.default_rng(5).standard_normal(len(t)) * (1 + 0.6 * np.sin(2 * np.pi * 0.7 * t))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    eng = Engine()
    eng.model = DetectModel("ar", 0.9)
    assert eng.transcribe(buf.getvalue(), None).text == ""


def test_hint_never_forces_language() -> None:
    lang, m = _run("ar", 0.9, "en")
    assert lang == "ar"
    assert m.used == [("ar", voice_app.PROMPTS["ar"])]
    assert _run("en", 0.9, "ar")[0] == "en"


def test_unknown_language_falls_back_to_hint() -> None:
    assert _run("fr", 0.3, "en")[0] == "en"
    assert _run("fr", 0.95, "en")[0] == "en"


def test_low_confidence_without_hint_is_arabic() -> None:
    assert _run("en", 0.3, None)[0] == "ar"
