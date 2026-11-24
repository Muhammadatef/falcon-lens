"""TTS engine adapters. Each returns (mono float32 samples, sample rate).

Heavy imports (mlx_audio) are lazy so the module imports in CI.
All models are read from FL_VOICE_MODELS (default ~/neo-models); nothing is downloaded.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import soundfile as sf

from .audio import Wave, resample, to_mono

MODELS = Path(os.environ.get("FL_VOICE_MODELS", str(Path.home() / "neo-models")))
DEFAULT_REF = "data/private/voice/ref_ar_ae.wav"

MACOS_VOICES = {"ar_ae": "Majed", "ar": "Majed", "en": "Daniel"}
KOKORO_VOICE_EN = "am_fenrir"


class Engine:
    name = ""

    def __init__(self, voice: str | None = None, ref: Path | None = None) -> None:
        self.voice = voice or ""
        self.ref = ref

    def label(self, lang: str) -> str:
        return self.voice

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        raise NotImplementedError


class MacOS(Engine):
    name = "macos"

    def label(self, lang: str) -> str:
        return self.voice or MACOS_VOICES.get(lang, "Daniel")

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        with tempfile.TemporaryDirectory() as d:
            wav = Path(d) / "o.wav"
            subprocess.run(
                ["say", "-v", self.label(lang), "--data-format=LEI16@24000", "-o", str(wav), text],
                check=True,
                timeout=90,
            )
            data, sr = sf.read(str(wav), dtype="float32")
        return to_mono(data), int(sr)


def _collect(gen: Any) -> Wave:
    return np.concatenate([np.array(r.audio, dtype=np.float32).reshape(-1) for r in gen])


class Kokoro(Engine):
    name = "kokoro"
    _model: Any = None

    def label(self, lang: str) -> str:
        return self.voice or KOKORO_VOICE_EN

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        if lang != "en":
            raise ValueError("kokoro is English-only here")
        if Kokoro._model is None:
            from mlx_audio.tts.utils import load

            Kokoro._model = load(str(MODELS / "Kokoro-82M"))
        m = Kokoro._model
        v = self.label(lang)
        return _collect(m.generate(text, voice=v, lang_code=v[0], speed=1.0)), int(m.sample_rate)


class Chatterbox(Engine):
    """Chatterbox multilingual v3 (MIT). Clones a reference clip if one is given,
    otherwise uses the conditionals bundled with the chatterbox-fp16 checkpoint
    (built-in voice)."""

    name = "chatterbox"
    _models: dict[str, Any] = {}

    def _load(self, builtin: bool) -> Any:
        key = "fp16" if builtin else "v3"
        if key not in Chatterbox._models:
            from mlx_audio.tts.utils import load

            Chatterbox._models[key] = load(
                str(MODELS / ("chatterbox-fp16" if builtin else "chatterbox-multilingual-v3"))
            )
        return Chatterbox._models[key]

    def label(self, lang: str) -> str:
        if self.voice:
            return self.voice
        return f"ref-{self.ref.stem}" if self.ref else "builtin"

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        import mlx.core as mx

        code = "ar" if lang.startswith("ar") else lang
        if self.ref is not None:
            m = self._load(builtin=False)
            data, sr = sf.read(str(self.ref), dtype="float32")
            ref = resample(to_mono(data), int(sr), int(m.sample_rate))
            gen = m.generate(text, ref_audio=mx.array(ref), lang_code=code, exaggeration=0.5, verbose=False)
        else:
            m = self._load(builtin=True)
            gen = m.generate(text, lang_code=code, exaggeration=0.5, verbose=False)
        return _collect(gen), int(m.sample_rate)


class VoiceTut(Engine):
    """VoiceTut-TTS (OmniVoice, Apache-2.0) with a bundled reference speaker (Egyptian-dialect refs)."""

    name = "voicetut"
    _model: Any = None

    def label(self, lang: str) -> str:
        return self.voice or "Shaker"

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        root = MODELS / "VoiceTut-TTS"
        refs = {r["speaker_name"]: r for r in json.loads((root / "reference_speakers/references.json").read_text())}
        spk = refs[self.label(lang)]
        if VoiceTut._model is None:
            from mlx_audio.tts.utils import load

            VoiceTut._model = load(str(root))
        m = VoiceTut._model
        gen = m.generate(
            text=text, ref_audio=str(root / spk["audio_path"]), ref_text=spk["reference_text"], num_steps=32
        )
        return _collect(gen), int(m.sample_rate)


class Silma(Engine):
    """SILMA TTS v1 (F5-TTS, Apache-2.0 weights). Runs in a separate torch venv:
    FL_SILMA_PYTHON=/path/to/venv/bin/python (see silma_worker.py). Needs --ref and FL_VOICE_REF_TEXT."""

    name = "silma"

    def label(self, lang: str) -> str:
        return self.voice or (f"ref-{self.ref.stem}" if self.ref else "ref")

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        py = os.environ.get("FL_SILMA_PYTHON")
        if not py:
            raise RuntimeError("silma: set FL_SILMA_PYTHON to a venv python with torch + silma-tts (--no-deps)")
        if self.ref is None:
            raise RuntimeError("silma needs --ref (reference wav) and FL_VOICE_REF_TEXT (its transcript)")
        with tempfile.TemporaryDirectory() as d:
            job = Path(d) / "job.json"
            job.write_text(
                json.dumps(
                    {
                        "ref": str(self.ref),
                        "ref_text": os.environ.get("FL_VOICE_REF_TEXT", ""),
                        "texts": [text],
                        "out_dir": str(Path(d) / "out"),
                    }
                )
            )
            subprocess.run(
                [py, "-m", "voice_clips.silma_worker", str(job)],
                check=True,
                capture_output=True,
                env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
                timeout=600,
            )
            data, sr = sf.read(str(Path(d) / "out" / "0.wav"), dtype="float32")
        return to_mono(data), int(sr)


class Polly(Engine):
    """Amazon Polly neural voice (ar-AE Zayd by default). Used ONLY offline to pre-generate clips from our
    own script text: no user data is ever sent, and nothing calls AWS at runtime. Credentials come from the
    environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_REGION), never from the repo."""

    name = "polly"
    VOICES = {"ar_ae": ("Zayd", "ar-AE"), "ar": ("Zayd", "ar-AE"), "en": ("Matthew", "en-US")}
    _client: Any = None

    def label(self, lang: str) -> str:
        return self.voice or self.VOICES.get(lang, self.VOICES["ar_ae"])[0]

    def synth(self, text: str, lang: str) -> tuple[Wave, int]:
        import boto3  # optional extra "polly"

        if Polly._client is None:
            Polly._client = boto3.client("polly", region_name=os.environ.get("AWS_REGION") or "us-east-1")
        code = self.VOICES.get(lang, self.VOICES["ar_ae"])[1]
        rate = 16000  # Polly PCM supports 8000 or 16000 only; generate.py resamples to the clip rate
        r = Polly._client.synthesize_speech(
            Text=text,
            VoiceId=self.label(lang),
            Engine="neural",
            OutputFormat="pcm",
            SampleRate=str(rate),
            LanguageCode=code,
        )
        pcm = np.frombuffer(r["AudioStream"].read(), dtype="<i2").astype(np.float32) / 32768.0
        return pcm, rate


ENGINES: dict[str, Callable[..., Engine]] = {
    "macos": MacOS,
    "kokoro": Kokoro,
    "chatterbox": Chatterbox,
    "voicetut": VoiceTut,
    "silma": Silma,
    "polly": Polly,
}


def make(name: str, voice: str | None = None, ref: Path | None = None) -> Engine:
    if name not in ENGINES:
        raise ValueError(f"unknown engine {name!r}; choose from {sorted(ENGINES)}")
    return ENGINES[name](voice=voice, ref=ref)


def default_ref() -> Path | None:
    p = Path(os.environ.get("FL_VOICE_REF_AR_AE", DEFAULT_REF))
    return p if p.is_file() else None


Samples = npt.NDArray[np.float32]
