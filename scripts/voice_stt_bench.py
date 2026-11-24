#!/usr/bin/env python3
"""Compare native STT candidates (model and decoding option) on the synthetic voice set: speed and word error rate.

What it does:
    Speaks the voice bench sentences with macOS `say` (English voices, Arabic voice Majed), then transcribes them
    in-process with the native engine's own decode path (services/voice-native/falcon_voice_native.py: language
    detection, per-language prompt, sample_len cap, temperature 0) for each candidate: large-v3-turbo as shipped,
    large-v3-turbo without timestamp tokens, whisper-small-mlx, whisper-small-mlx without timestamps. Records the
    median and p95 decode time and the word error rate per language against the sentence that was spoken.
    No audio and no transcripts are kept: only the aggregates are written.
When to use it:
    To choose FL_WHISPER_PATH / FL_WHISPER_NO_TIMESTAMPS for the native engine. The default stays unchanged unless
    a candidate is faster AND its Arabic WER is not worse.
How to run (needs the native service environment, macOS `say`, ffmpeg and network for the first model download):
    uv run --project services/voice-native python scripts/voice_stt_bench.py [--repeats 3] [--no-publish]
Outputs:
    evals/results/published/voice/stt_models_<UTC>.json, labelled SYNTHETIC.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "services" / "voice-native"))
import falcon_voice_native as native  # noqa: E402
from voice_bench import AR_VOICE, EN_VOICES, OUT, SET, tts  # noqa: E402

from falcon_core.voice.textnorm import normalise  # noqa: E402

TURBO = native.model_path()
SMALL = "mlx-community/whisper-small-mlx"
CANDIDATES: list[tuple[str, str, bool]] = [
    ("turbo (shipped)", TURBO, False),
    ("turbo, no timestamp tokens", TURBO, True),
    ("small-mlx", SMALL, False),
    ("small-mlx, no timestamp tokens", SMALL, True),
]


def wer(ref: str, hyp: str) -> tuple[int, int]:
    """(word edit distance, reference words) on normalised text (Arabic letters folded, punctuation dropped)."""
    r, h = normalise(ref).split(), normalise(hyp).split()
    prev = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        cur = [i]
        for j, b in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1], len(r)


def pct(values: list[float], q: float) -> float:
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round(q * (len(s) - 1))))], 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()
    clips: list[tuple[str, str, np.ndarray]] = []
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for i, (lang, text, _w, _i) in enumerate(SET):
            for voice in EN_VOICES if lang == "en" else (AR_VOICE,):
                with wave.open(str(tts(text, voice, d, f"c{i}_{voice}")), "rb") as w:
                    pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
                clips.append((lang, text, pcm))
    results = []
    for name, path, no_ts in CANDIDATES:
        native.WHISPER = path
        native.NO_TIMESTAMPS = no_ts
        native.transcribe(clips[0][2], None)  # warm-up, not counted
        lat: dict[str, list[float]] = {"en": [], "ar": []}
        err: dict[str, list[int]] = {"en": [0, 0], "ar": [0, 0]}
        for lang, ref, pcm in clips:
            for r in range(a.repeats):
                t0 = time.perf_counter()
                text, _ = native.transcribe(pcm, None)
                lat[lang].append((time.perf_counter() - t0) * 1000)
                if r == 0:
                    e, n = wer(ref, text)
                    err[lang][0] += e
                    err[lang][1] += n
        results.append(
            {
                "candidate": name,
                "model": "whisper-large-v3-turbo" if path == TURBO else SMALL.split("/")[1],
                "no_timestamps": no_ts,
                "decode_ms": {
                    k: {"n": len(v), "p50": pct(v, 0.5), "p95": pct(v, 0.95), "mean": round(statistics.mean(v), 1)}
                    for k, v in lat.items()
                },
                "wer": {k: round(e / n, 4) for k, (e, n) in err.items()},
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    base = results[0]
    for r in results:
        r["faster_than_shipped"] = r["decode_ms"]["ar"]["p50"] < base["decode_ms"]["ar"]["p50"]  # type: ignore[index]
        r["arabic_wer_not_worse"] = r["wer"]["ar"] <= base["wer"]["ar"]  # type: ignore[index]
    doc = {
        "kind": "voice_stt_models",
        "provenance": "SYNTHETIC: speech generated by macOS `say` (TTS), not human recordings. Decode time only: upload and network are not included.",  # noqa: E501
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "clips": len(clips),
        "repeats": a.repeats,
        "candidates": results,
    }
    if not a.no_publish:
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"stt_models_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
