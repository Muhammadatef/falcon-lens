from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from voice_clips import audio, engines
from voice_clips.script import (
    MANIFEST_KEYS,
    Clip,
    load_script,
    manifest_entry,
    validate_manifest,
    write_manifest,
)

HERE = Path(__file__).resolve().parents[1]
RATE = 24000


def tone(seconds: float = 1.0, amp: float = 0.05, lead: float = 0.3) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    x = (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return np.concatenate([np.zeros(int(RATE * lead), np.float32), x, np.zeros(int(RATE * lead), np.float32)])


def test_loudness_normalised_to_target() -> None:
    y = audio.process(tone(2.0, amp=0.02), RATE)
    assert abs(audio.loudness_lufs(y, RATE) - audio.TARGET_LUFS) < 1.0
    assert float(np.max(np.abs(y))) <= audio.CEILING + 1e-6


def test_loud_input_is_brought_down() -> None:
    y = audio.process(tone(2.0, amp=0.9), RATE)
    assert abs(audio.loudness_lufs(y, RATE) - audio.TARGET_LUFS) < 1.5 or float(np.max(np.abs(y))) <= audio.CEILING


def test_trim_and_fades() -> None:
    x = tone(1.0, lead=0.5)
    y = audio.process(x, RATE)
    assert y.size < x.size - RATE * 0.6  # most of the 1 s of padding removed
    n = int(RATE * audio.FADE_MS / 1000)
    assert y[0] == 0.0 and y[-1] == 0.0
    assert abs(y[n // 2]) < abs(y[n * 3])  # ramp rising


def test_mono_and_resample() -> None:
    stereo = np.stack([tone(0.5), tone(0.5)], axis=1)
    assert audio.to_mono(stereo).ndim == 1
    y = audio.resample(tone(1.0), RATE, 22050)
    assert abs(y.size - 22050 * (len(tone(1.0)) / RATE)) < 5


def test_encoder_and_ms(tmp_path: Path) -> None:
    ext = audio.encoder_ext()
    assert ext in ("mp3", "ogg")
    y = audio.process(tone(1.0), RATE)
    p = tmp_path / f"a.{ext}"
    audio.encode(y, RATE, p)
    assert p.stat().st_size > 500
    assert audio.duration_ms(y, RATE) == pytest.approx(1000 * y.size / RATE, abs=1)


def test_script_loading_and_errors(tmp_path: Path) -> None:
    clips = load_script(HERE / "draft_script.yaml")
    assert len(clips) >= 20
    assert {c.lang for c in clips} == {"ar_ae", "en"}
    bad = tmp_path / "bad.yaml"
    bad.write_text("clips:\n  - {id: a, lang: fr, text: x}\n")
    with pytest.raises(ValueError, match="lang"):
        load_script(bad)
    dup = tmp_path / "dup.yaml"
    dup.write_text("clips:\n  - {id: a, lang: en, text: x}\n  - {id: a, lang: en, text: y}\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_script(dup)


def test_manifest_schema_and_coverage(tmp_path: Path) -> None:
    clips = [Clip("a", "en", "hi"), Clip("b", "en", "yo")]
    m = [manifest_entry(c, f"{c.id}.mp3", 1200, "macos", "Daniel") for c in clips]
    validate_manifest(m, clips)
    assert tuple(m[0]) == MANIFEST_KEYS
    with pytest.raises(ValueError, match="missing"):
        validate_manifest(m[:1], clips)
    with pytest.raises(ValueError, match="ms"):
        validate_manifest([{**m[0], "ms": 0}, m[1]], clips)
    path = write_manifest(tmp_path, m)
    assert json.loads(path.read_text())[0]["id"] == "a"


def test_committed_manifests_cover_draft_or_final_script() -> None:
    """Every committed manifest entry points at a file that exists and has the full key set."""
    root = HERE.parents[1] / "web/public/voice"
    for lang_dir in root.glob("*/"):
        m = json.loads((lang_dir / "manifest.json").read_text())
        for e in m:
            assert tuple(e) == MANIFEST_KEYS
            assert (lang_dir / e["file"]).is_file()
            # clones of real people stay in data/private; committed clips are built-in/synthetic voices only
            assert not str(e["voice"]).startswith("ref-"), e["id"]


def test_engine_registry_and_default_ref(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert {"macos", "kokoro", "chatterbox", "silma", "voicetut"} <= set(engines.ENGINES)
    with pytest.raises(ValueError):
        engines.make("nope")
    monkeypatch.setenv("FL_VOICE_REF_AR_AE", str(tmp_path / "missing.wav"))
    assert engines.default_ref() is None
    f = tmp_path / "r.wav"
    f.write_bytes(b"x")
    monkeypatch.setenv("FL_VOICE_REF_AR_AE", str(f))
    assert engines.default_ref() == f
    assert engines.make("macos").label("ar_ae") == "Majed"
    assert engines.make("macos").label("en") == "Daniel"
