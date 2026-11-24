#!/usr/bin/env python3
"""Benchmark the voice STT engines on a SYNTHETIC set (macOS `say` text-to-speech) and publish an artifact.

What it does:
    Generates speech with macOS `say` (English voices and the Arabic voice Majed), converts it with ffmpeg to
    16 kHz wav, sends each clip to every engine URL given (POST /stt), runs the deterministic wake + intent
    logic on the transcript and records latency and wake / intent accuracy. Writes
    evals/results/published/voice/<UTC timestamp>.json, labelled SYNTHETIC. Nothing is stored except that
    summary: no audio and no transcripts are kept (only per-clip pass/fail and timings).

When to use it:
    To pick the Whisper model and to publish the latency and wake-accuracy numbers.

How to run:
    uv run python scripts/voice_bench.py --engine native=http://127.0.0.1:8093 --engine container=http://127.0.0.1:18094 \
        [--token T] [--repeats 3] [--no-publish]
    (one artifact per container model: restart the container with FL_WHISPER_MODEL=<m> and run again)

Inputs:
    Engine URLs (a running native service and/or container service), optional bearer token, macOS `say`, ffmpeg.
Outputs / side effects:
    The artifact JSON (unless --no-publish). Skips with a clear message when `say` or the Arabic voice is missing.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from falcon_core.voice.intent import analyse

DEBUG = False
OUT = Path(__file__).resolve().parents[1] / "evals" / "results" / "published" / "voice"

# (language, voice, text, expected wake, expected intent)
EN_VOICES = ("Samantha", "Daniel")
AR_VOICE = "Majed"
SET: list[tuple[str, str, bool, str]] = [
    (
        "en",
        "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens",
        True,
        "check_clipboard",
    ),
    ("en", "Hey Falcon, check the link I copied", True, "check_clipboard"),
    ("en", "Hi Falcon, I got a suspicious email", True, "check_clipboard"),
    ("en", "OK Falcon, what can you do", True, "help"),
    ("en", "Hey Falcon, stop", True, "stop"),
    ("en", "Falcon Lens, scan this message", True, "check_clipboard"),
    ("en", "The weather is nice today and I am going for a walk", False, "none"),
    ("en", "Please remind me to buy some milk", False, "none"),
    ("ar", "يا فالكون، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر", True, "check_clipboard"),
    ("ar", "يا فالكون افحص الرابط الذي نسخته", True, "check_clipboard"),
    ("ar", "هلا فالكون وصلتني رسالة مشبوهة", True, "check_clipboard"),
    ("ar", "هاي فالكون ماذا تفعل", True, "help"),
    ("ar", "يا صقر توقف", True, "stop"),
    ("ar", "عدسة الصقر افحص هذه الرسالة", True, "check_clipboard"),
    ("ar", "الطقس جميل اليوم وسأذهب في نزهة", False, "none"),
    ("ar", "من فضلك ذكرني بشراء الحليب", False, "none"),
]


def tts(text: str, voice: str, d: Path, name: str) -> Path:
    aiff, wav = d / f"{name}.aiff", d / f"{name}.wav"
    subprocess.run(["say", "-v", voice, "-o", str(aiff), text], check=True, timeout=60)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000", str(wav)], check=True, timeout=60
    )
    return wav


def voices() -> set[str]:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, check=True).stdout
    return {line.split("  ")[0].split(" (")[0].strip() for line in out.splitlines() if line.strip()}


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def run_engine(
    name: str, url: str, token: str, clips: list[tuple[str, Path, bool, str]], repeats: int
) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    lat: dict[str, list[float]] = {"en": [], "ar": []}
    wake_ok = intent_ok = n = 0
    fp = neg = 0
    errors: dict[str, int] = {}
    models: set[str] = set()
    with httpx.Client(timeout=120) as c:
        # warm-up (not counted): the container loads its model lazily, the native engine warms on start
        c.post(f"{url}/stt", content=clips[0][1].read_bytes(), headers={**headers, "Content-Type": "audio/wav"})
        for lang, wav, want_wake, want_intent in clips:
            for r in range(repeats):
                t0 = time.perf_counter()
                resp = c.post(f"{url}/stt", content=wav.read_bytes(), headers={**headers, "Content-Type": "audio/wav"})
                wall = (time.perf_counter() - t0) * 1000
                if resp.status_code != 200:  # e.g. 504: the engine hit its 25 s limit; a failed clip counts as a miss
                    errors[str(resp.status_code)] = errors.get(str(resp.status_code), 0) + 1
                    if r == 0:
                        n += 1
                        neg += not want_wake
                    continue
                body = resp.json()
                models.add(str(body.get("model")))
                lat[lang].append(wall)
                if r == 0:
                    res = analyse(str(body["text"]))
                    n += 1
                    wake_ok += res.wake == want_wake
                    intent_ok += res.intent == want_intent
                    if DEBUG and (res.wake != want_wake or res.intent != want_intent):
                        print(
                            f"DEBUG miss [{name}/{lang}] heard={body['text']!r} got={res.wake},{res.intent}"
                        )  # local only
                    if not want_wake:
                        neg += 1
                        fp += res.wake
    return {
        "engine": name,
        "models": sorted(models),
        "clips": n,
        "wake_accuracy": round(wake_ok / n, 3) if n else None,
        "intent_accuracy": round(intent_ok / n, 3) if n else None,
        "false_wake": f"{fp}/{neg}",
        "errors_by_status": errors,
        "latency_ms": {
            k: {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "mean": round(statistics.mean(v), 1)}
            for k, v in lat.items()
            if v
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", action="append", required=True, help="name=url, e.g. native=http://127.0.0.1:8093")
    ap.add_argument("--token", default="")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--no-publish", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print mismatching transcripts (local terminal only)")
    a = ap.parse_args()
    global DEBUG
    DEBUG = a.debug
    if shutil.which("say") is None or shutil.which("ffmpeg") is None:
        print("SKIP: macOS `say` and ffmpeg are needed to generate the synthetic set")
        return 0
    have = voices()
    if AR_VOICE not in have:
        print(f"SKIP: Arabic voice {AR_VOICE} is not installed (System Settings > Accessibility > Spoken Content)")
        return 0
    results = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        clips: list[tuple[str, Path, bool, str]] = []
        for i, (lang, text, wake, intent) in enumerate(SET):
            vs = [v for v in EN_VOICES if v in have] if lang == "en" else [AR_VOICE]
            for v in vs:
                clips.append((lang, tts(text, v, d, f"c{i}_{v}"), wake, intent))
        for spec in a.engine:
            name, url = spec.split("=", 1)
            results.append(run_engine(name, url.rstrip("/"), a.token, clips, a.repeats))
    doc = {
        "kind": "voice_bench",
        "provenance": "SYNTHETIC: speech generated by macOS `say` (TTS), not human recordings. Real microphones will differ.",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "clips": len(clips),
        "repeats": a.repeats,
        "voices": {"en": [v for v in EN_VOICES if v in have], "ar": [AR_VOICE]},
        "engines": results,
    }
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    if not a.no_publish:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
