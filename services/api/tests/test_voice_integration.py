"""Real speech (macOS `say`, synthetic) through a real STT engine and the API route.

Set FL_VOICE_INTEGRATION_URLS (e.g. native=http://127.0.0.1:8093,container=http://127.0.0.1:18094) and
FL_VOICE_TOKEN to run. Skipped, with the reason, when no engine URL is set, `say` / ffmpeg are missing or the
Arabic voice (Majed) is not installed. Scratch compose project only: see docs/RUNBOOK.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import fakeredis
import httpx
import pytest

from falcon_api.app import build_app
from falcon_api.auth import Authenticator, MemoryKeyStore
from falcon_api.voice import SttRouter, parse_engines
from tests.conftest import FakeStore, make_settings

pytestmark = pytest.mark.integration

URLS = os.environ.get("FL_VOICE_INTEGRATION_URLS", "")
EN = "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens"
AR = "يا فالكون، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر"


def have_voice(name: str) -> bool:
    if shutil.which("say") is None:
        return False
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=False).stdout
    return name in out


def speak(text: str, voice: str, tmp: Path) -> bytes:
    aiff, wav = tmp / "s.aiff", tmp / "s.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, timeout=60)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", str(wav)], check=True, timeout=60
    )
    return wav.read_bytes()


@pytest.mark.skipif(not URLS, reason="FL_VOICE_INTEGRATION_URLS not set (needs a running STT engine)")
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize(
    ("voice", "text", "lang"),
    [("Samantha", EN, "en"), ("Daniel", EN, "en"), ("Majed", AR, "ar")],
)
async def test_demo_lines_wake_and_intent(voice: str, text: str, lang: str, tmp_path: Path) -> None:
    if not have_voice(voice):
        pytest.skip(f"macOS voice {voice} is not installed")
    audio = speak(text, voice, tmp_path)
    keystore = MemoryKeyStore()
    key = (await Authenticator(keystore, "test-pepper").create("web", ["read"], 1000))[1]
    router = SttRouter(parse_engines(URLS), os.environ.get("FL_VOICE_TOKEN", ""), httpx.AsyncClient(timeout=120))
    app = build_app(
        make_settings(fl_rate_limit_per_ip_per_min=1000),
        redis=fakeredis.FakeAsyncRedis(decode_responses=True),
        store=FakeStore(),
        keystore=keystore,
        stt_router=router,
    )
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as c:
        r = await c.post(
            "/v1/voice/utterance", files={"audio": ("s.wav", audio, "audio/wav")}, headers={"X-API-Key": key}
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lang"] == lang
    assert body["wake"] is True
    assert body["intent"] == "check_clipboard"
