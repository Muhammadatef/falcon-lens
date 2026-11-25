"""Container decode path: forced demuxer from magic bytes, no probing, bounded memory, fail-closed token."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from falcon_voice.app import Engine, build_app, decode


def test_playlist_like_and_unknown_payloads_are_refused() -> None:
    for body in (
        b"ffconcat version 1.0\nfile '/some/local/file'\n",
        b"#EXTM3U\nhttp://internal.example/\n",
        b"<?xml version='1.0'?><MPD/>",
        b"ID3\x03\x00\x00\x00\x00\x00\x00",
    ):
        with pytest.raises(ValueError):
            decode(body)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed (only used to make test audio)")
@pytest.mark.parametrize(
    ("ext", "codec"), [("webm", "libopus"), ("ogg", "libvorbis"), ("wav", "pcm_s16le"), ("mp4", "aac"), ("aac", "aac")]
)
def test_real_containers_decode_in_memory(ext: str, codec: str, tmp_path: Path) -> None:
    out = tmp_path / f"t.{ext}"
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1.5",
        "-c:a",
        codec,
        *(["-movflags", "frag_keyframe+empty_moov"] if ext == "mp4" else []),  # what iOS Safari records
        str(out),
    ]
    r = subprocess.run(cmd, capture_output=True, check=False)  # noqa: S603
    if r.returncode != 0:
        pytest.skip(f"this ffmpeg has no {codec} encoder")
    audio = decode(out.read_bytes())
    assert 1.3 < len(audio) / 16000 < 1.7


def test_missing_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FL_VOICE_TOKEN", raising=False)
    monkeypatch.setenv("FL_VOICE_PRELOAD", "false")
    c = TestClient(build_app(Engine()))
    assert c.get("/healthz").status_code == 200
    assert c.post("/stt", content=b"x").status_code == 503


def test_offline_with_no_model_reports_error_and_never_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FL_VOICE_OFFLINE", "true")
    eng = Engine()
    calls: list[bool] = []

    def fake_open(*, local_only: bool) -> object:
        calls.append(local_only)
        raise FileNotFoundError

    monkeypatch.setattr(eng, "_open", fake_open)
    eng.load()
    assert calls == [True]
    assert eng.error == "model_missing_offline"
    assert not eng.loaded


def test_present_model_loads_locally_without_download(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = Engine()
    calls: list[bool] = []

    def fake_open(*, local_only: bool) -> object:
        calls.append(local_only)
        return object()

    monkeypatch.setattr(eng, "_open", fake_open)
    eng.load()
    assert calls == [True]
    assert eng.loaded


def test_missing_model_downloads_once_then_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    eng = Engine()
    calls: list[bool] = []

    def fake_open(*, local_only: bool) -> object:
        calls.append(local_only)
        if local_only:
            raise FileNotFoundError
        return object()

    monkeypatch.setattr(eng, "_open", fake_open)
    eng.load()
    assert calls == [True, False]
    assert eng.loaded
