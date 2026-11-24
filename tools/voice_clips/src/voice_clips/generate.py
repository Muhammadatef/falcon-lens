"""CLI: render every clip of a given language into web/public/voice/<lang>/.

uv run --extra mlx python -m voice_clips.generate --engine macos --lang ar_ae \
    --script draft_script.yaml --out ../../web/public/voice/ar_ae
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import audio, engines
from .script import Clip, load_script, manifest_entry, validate_manifest, write_manifest

REPO_SCRIPT = "packages/falcon_core/src/falcon_core/i18n/voice_script.yaml"
REPO_FAQ_SCRIPT = "packages/falcon_core/src/falcon_core/i18n/voice_faq.yaml"


def render(
    clips: list[Clip],
    eng: engines.Engine,
    lang: str,
    out: Path,
    rate: int = audio.DEFAULT_RATE,
) -> list[dict[str, object]]:
    ext = audio.encoder_ext()
    out.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for c in clips:
        t0 = time.time()
        raw, sr = eng.synth(c.text, lang)
        wav = audio.process(raw, sr, rate)
        name = f"{c.id}.{ext}"
        audio.encode(wav, rate, out / name)
        print(f"{c.id}: {time.time() - t0:.1f}s gen+encode, {audio.duration_ms(wav, rate)} ms audio", flush=True)
        manifest.append(manifest_entry(c, name, audio.duration_ms(wav, rate), eng.name, eng.label(lang)))
    return manifest


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--engine", required=True, choices=sorted(engines.ENGINES))
    p.add_argument("--lang", required=True, choices=["ar_ae", "en"])
    p.add_argument(
        "--ref", type=Path, default=None, help="reference wav (cloning). Default: FL_VOICE_REF_AR_AE if present"
    )
    p.add_argument("--voice", default=None)
    p.add_argument(
        "--script",
        type=Path,
        action="append",
        default=None,
        help="script yaml (repeatable). Default: voice_script.yaml plus voice_faq.yaml (one manifest per language)",
    )
    p.add_argument(
        "--merge",
        action="store_true",
        help="keep clips already in <out>/manifest.json (same id and text) and render only the new or changed ones",
    )
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--rate", type=int, default=audio.DEFAULT_RATE, choices=[22050, 24000])
    a = p.parse_args(argv)

    ref = a.ref
    if ref is None and a.engine in ("chatterbox", "silma") and a.lang == "ar_ae":
        ref = engines.default_ref()
    if ref is not None and not ref.is_file():
        print(f"reference clip not found: {ref}", file=sys.stderr)
        return 2
    scripts = a.script or [Path(REPO_SCRIPT), Path(REPO_FAQ_SCRIPT)]
    clips = [c for path in scripts for c in load_script(path) if c.lang == a.lang]
    if not clips:
        print(f"no clips for lang {a.lang} in {', '.join(map(str, scripts))}", file=sys.stderr)
        return 2
    if len({c.id for c in clips}) != len(clips):
        print("duplicate clip ids across the script files", file=sys.stderr)
        return 2
    eng = engines.make(a.engine, voice=a.voice, ref=ref)
    kept: dict[str, dict[str, object]] = {}
    todo = clips
    if a.merge and (a.out / "manifest.json").is_file():
        old = {m["id"]: m for m in json.loads((a.out / "manifest.json").read_text(encoding="utf-8"))}
        kept = {c.id: old[c.id] for c in clips if c.id in old and old[c.id]["text"] == c.text}
        todo = [c for c in clips if c.id not in kept]
        print(f"merge: keeping {len(kept)} clips, rendering {len(todo)}", flush=True)
    fresh = {str(m["id"]): m for m in render(todo, eng, a.lang, a.out, a.rate)} if todo else {}
    manifest = [kept.get(c.id) or fresh[c.id] for c in clips]
    validate_manifest(manifest, clips)
    write_manifest(a.out, manifest)
    print(f"wrote {len(manifest)} clips to {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
