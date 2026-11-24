"""Native STT hardening: forced demuxer, no probing of playlist-like payloads, fail-closed token."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load(monkeypatch: pytest.MonkeyPatch, token: str | None) -> Any:
    if token is None:
        monkeypatch.delenv("FL_VOICE_TOKEN", raising=False)
    else:
        monkeypatch.setenv("FL_VOICE_TOKEN", token)
    monkeypatch.setenv("FL_WHISPER_PATH", "/nonexistent/whisper")
    sys.modules.pop("falcon_voice_native", None)
    return importlib.import_module("falcon_voice_native")


def test_playlist_like_payloads_never_reach_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load(monkeypatch, "t0ken")

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("ffmpeg must not run")

    monkeypatch.setattr(mod.subprocess, "run", boom)
    c = TestClient(mod.app)
    h = {"Authorization": "Bearer t0ken"}
    for body in (b"ffconcat version 1.0\nfile '/some/local/file'\n", b"#EXTM3U\nhttp://internal.example/\n"):
        for ct in ("audio/wav", "audio/webm", "audio/ogg", "text/plain"):
            assert c.post("/stt", content=body, headers={**h, "Content-Type": ct}).status_code == 422


def test_ffmpeg_command_is_hardened(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load(monkeypatch, "t0ken")
    seen: dict[str, Any] = {}

    class R:
        stdout = b"\x00\x00" * 160

    def fake_run(cmd: list[str], **kw: Any) -> R:
        seen["cmd"], seen["kw"] = cmd, kw
        return R()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    wav = b"RIFF\x00\x00\x00\x00WAVEfmt "
    mod.decode(wav, "audio/wav")
    cmd = seen["cmd"]
    assert cmd[cmd.index("-protocol_whitelist") + 1] == "pipe"
    assert cmd[cmd.index("-f") + 1] == "wav"
    assert cmd[cmd.index("-t") + 1] == "15.5"
    assert not seen["kw"].get("shell")
    assert seen["kw"]["timeout"] == 20
    with pytest.raises(ValueError):  # declared webm but the bytes are wav
        mod.decode(wav, "audio/webm")


def test_missing_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = load(monkeypatch, None)
    c = TestClient(mod.app)
    assert c.get("/healthz").status_code == 200
    assert c.post("/stt", content=b"x").status_code == 503


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize(
    ("ctype", "args", "ext"),
    [("audio/mp4", ["-movflags", "frag_keyframe+empty_moov"], "mp4"), ("audio/aac", [], "aac")],
)
def test_ios_formats_decode_through_forced_demuxer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ctype: str, args: list[str], ext: str
) -> None:
    mod = load(monkeypatch, "t0ken")
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
        "aac",
        *args,
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603
    audio = mod.decode(out.read_bytes(), ctype)
    assert 1.3 < len(audio) / 16000 < 1.7
    with pytest.raises(ValueError):  # declared mp4 but the bytes are aac (and vice versa)
        mod.decode(out.read_bytes(), "audio/aac" if ext == "mp4" else "audio/mp4")
