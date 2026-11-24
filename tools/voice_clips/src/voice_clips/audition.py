"""Render the same Emirati sentences with every available Arabic engine/voice for owner listening.

Output (private, untracked): <out>/<engine>-<voice>-<n>.mp3 and timings.json.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from . import audio, engines

SENTENCES = [
    "هلا والله، أنا صقر. ألصق الرابط أو الرسالة وأنا أفحصها لك.",
    "ثواني، أفحص لك الموضوع.",
    "انتبه، هذا الرابط احتيال على الأغلب. لا تفتحه ولا تدخل أي بيانات.",
    "فيه علامات مريبة. الأفضل لا تتعامل معه، وتتأكد من الجهة الرسمية.",
    "ما لقينا علامات تحذير، لكن خلك حذر دايماً.",
    "لا تشارك رقم بطاقتك ولا الرمز السري مع أي أحد.",
]
VOICETUT_SPEAKERS = ["Shaker", "Ahmed", "Hassan", "Hanan"]


def synthetic_ref(dirpath: Path) -> Path:
    """A reference wav made by macOS Majed (synthetic, no real person) for cloning-style engines."""
    ref = dirpath / "ref_majed.wav"
    subprocess.run(["say", "-v", "Majed", "--data-format=LEI16@24000", "-o", str(ref), SENTENCES[0]], check=True)
    return ref


def run_one(eng: engines.Engine, out: Path, results: list[dict[str, object]]) -> None:
    ext = audio.encoder_ext()
    tag = f"{eng.name}-{eng.label('ar_ae')}"
    for i, text in enumerate(SENTENCES, 1):
        t0 = time.time()
        try:
            raw, sr = eng.synth(text, "ar_ae")
        except Exception as e:  # keep going; record the failure for the README
            results.append(
                {"engine": eng.name, "voice": eng.label("ar_ae"), "n": i, "error": f"{type(e).__name__}: {e}"}
            )
            print(f"{tag}-{i}: FAILED {type(e).__name__}: {e}", flush=True)
            return
        gen_s = time.time() - t0
        wav = audio.process(raw, sr)
        audio.encode(wav, audio.DEFAULT_RATE, out / f"{tag}-{i}.{ext}")
        rec = {
            "engine": eng.name,
            "voice": eng.label("ar_ae"),
            "n": i,
            "gen_s": round(gen_s, 2),
            "audio_ms": audio.duration_ms(wav, audio.DEFAULT_RATE),
        }
        results.append(rec)
        print(f"{tag}-{i}: {gen_s:.1f}s -> {rec['audio_ms']} ms", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument(
        "--only", nargs="*", default=None, help="subset: macos chatterbox-builtin chatterbox-ref voicetut silma"
    )
    a = p.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    want = set(a.only) if a.only else {"macos", "chatterbox-builtin", "chatterbox-ref", "voicetut", "silma"}
    with tempfile.TemporaryDirectory() as d:
        ref = synthetic_ref(Path(d))
        if "macos" in want:
            run_one(engines.make("macos", voice="Majed"), a.out, results)
        if "chatterbox-builtin" in want:
            run_one(engines.make("chatterbox"), a.out, results)
        if "chatterbox-ref" in want:
            run_one(engines.make("chatterbox", voice="clone-majed-synthetic", ref=ref), a.out, results)
        if "voicetut" in want:
            for s in VOICETUT_SPEAKERS:
                run_one(engines.make("voicetut", voice=s), a.out, results)
        if "silma" in want:
            os.environ["FL_VOICE_REF_TEXT"] = SENTENCES[0]
            run_one(engines.make("silma", voice="clone-majed-synthetic", ref=ref), a.out, results)
    old = a.out / "timings.json"
    prev = json.loads(old.read_text()) if old.exists() else []
    old.write_text(json.dumps(prev + results, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
