#!/usr/bin/env python3
"""Live end-to-end test of the "Hey Falcon" voice assistant: macOS speech into a real browser against a running stack.

What it does:
    1. Makes the owner's demo lines as wav files with macOS `say` (English: Samantha, Arabic: Majed), padded with
       silence so the fake microphone says nothing before or after.
    2. Runs the Playwright suite `web/tests/live/voice.live.ts` (@voice-live) once per language. Chromium starts with
       --use-fake-device-for-media-stream and --use-file-for-fake-audio-capture=<wav>, the clipboard holds three
       Falcon Demo Bank test messages, and the suite asserts wake, three checks, the Sentinel card or "still watching",
       narration in the right language, the public /history Voice badge, Prometheus and Phoenix evidence.
    3. Writes reviews/VOICE-E2E-<date>.md from what the suites measured (verdicts, engines, counts). No transcript and
       no audio is kept: the wav files live in a temp folder that is deleted at the end.

When to use it:
    After `make up` (or on a scratch stack), before the demo, and after any change to the voice, check or event path.
    It is NOT part of CI or `make test`: it needs macOS `say`, a browser and a running stack.

How to run:
    make voice-e2e          (defaults: https://localhost:8443, Prometheus :9090, Phoenix :6006)
    BASE_URL=https://localhost:48443 PROM_URL=http://127.0.0.1:49090 \\
        PHOENIX_URL=http://127.0.0.1:46006 PHOENIX_ADMIN_SECRET=... make voice-e2e
    uv run python scripts/voice_e2e.py --langs en --no-review

Inputs:
    --base-url / BASE_URL     gateway of the stack under test (TLS errors are ignored: local CA)
    --prom-url / PROM_URL     Prometheus (read-only queries); "" skips the step with a reason
    --phoenix-url / PHOENIX_URL  Phoenix (read-only); key from PHOENIX_API_KEY or PHOENIX_ADMIN_SECRET in the
                              environment, else read from .env (never printed); "" skips the step with a reason
    --langs                   comma list of en,ar (default en,ar)
    --review PATH             where to write the review file (default reviews/VOICE-E2E-<date>.md)

Outputs / side effects:
    The review file, a temp folder (removed), and the browser traffic against the stack: three checks per language
    through the public API (channel "voice"), which show up in History as real, labelled entries. Exit 0 only when
    every language passed; a skipped optional step (Prometheus, Phoenix) is reported, not hidden.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# The owner's demo lines (same as `make voice-rehearsal`).
LINES = {
    "en": ("Samantha", "Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens"),
    "ar": ("Majed", "يا صقر، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر"),
}
RATE = 16000
LEAD_S = 3.0  # silence before the line: the listener is up before the speech starts
TAIL_S = 60.0  # silence after it: the fake microphone must not repeat or say anything else


def env_value(name: str) -> str:
    """A value from the environment, else from .env (read, never printed)."""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if env.is_file():
        m = re.search(rf"^{name}=(.*)$", env.read_text(encoding="utf-8"), re.M)
        if m:
            return m.group(1).strip()
    return ""


def make_wav(lang: str, out: Path) -> bool:
    voice, text = LINES[lang]
    raw = out.with_suffix(".raw.wav")
    cmd = ["say", "-v", voice, "--data-format=LEI16@16000", "-o", str(raw), text]
    if subprocess.run(cmd, capture_output=True, check=False).returncode != 0:  # noqa: S603
        print(f"{lang}: `say -v {voice}` failed (Settings > Accessibility > Spoken Content > System voice, install it)")
        return False
    with wave.open(str(raw), "rb") as r:
        params, frames = r.getparams(), r.readframes(r.getnframes())
    if (params.framerate, params.sampwidth, params.nchannels) != (RATE, 2, 1):
        print(f"{lang}: unexpected wav format from `say`: {params}")
        return False
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * int(RATE * LEAD_S) + frames + b"\x00\x00" * int(RATE * TAIL_S))
    raw.unlink()
    return True


def run_lang(lang: str, wav: Path, args: argparse.Namespace, result: Path) -> tuple[int, dict]:
    env = {
        **os.environ,
        "VOICE_E2E_WAV": str(wav),
        "VOICE_E2E_LANG": lang,
        "VOICE_E2E_RESULT": str(result),
        "BASE_URL": args.base_url,
        "PROM_URL": args.prom_url,
        "PHOENIX_URL": args.phoenix_url,
        "PHOENIX_API_KEY": env_value("PHOENIX_API_KEY"),
        "PHOENIX_ADMIN_SECRET": env_value("PHOENIX_ADMIN_SECRET"),
    }
    cmd = ["pnpm", "exec", "playwright", "test", "--project=voice-live", "--reporter=list"]
    code = subprocess.run(cmd, cwd=WEB, env=env, check=False).returncode  # noqa: S603, S607
    data = json.loads(result.read_text()) if result.is_file() else {}
    return code, data


def review(path: Path, args: argparse.Namespace, runs: list[tuple[str, int, dict]]) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        f"# Voice assistant, live end-to-end run ({now})",
        "",
        f"Stack under test: `{args.base_url}`. Test: `web/tests/live/voice.live.ts` (@voice-live), "
        "driven by `scripts/voice_e2e.py`.",
        "Speech: macOS `say` (English: Samantha, Arabic: Majed), played to Chromium through a fake microphone. "
        "Messages: three Falcon Demo Bank test fixtures on the clipboard. "
        "No transcript and no audio is stored by the test.",
        "",
    ]
    for lang, code, data in runs:
        out += [f"## {lang.upper()}: {'PASSED' if code == 0 else 'FAILED'}", ""]
        out += ["| Step | Result | Detail |", "|---|---|---|"]
        for s in data.get("steps", []):
            out.append(f"| {s['name']} | {s['status']} | {str(s['detail']).replace('|', '/')} |")
        if not data.get("steps"):
            out.append("| (no result written) | failed | the suite did not start; see the console output |")
        out.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"review written: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")


def main() -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    ap = argparse.ArgumentParser(description="Live end-to-end test of the Hey Falcon voice assistant")
    ap.add_argument("--base-url", default=os.environ.get("BASE_URL", "https://localhost:8443"))
    ap.add_argument("--prom-url", default=os.environ.get("PROM_URL", "http://127.0.0.1:9090"))
    ap.add_argument("--phoenix-url", default=os.environ.get("PHOENIX_URL", "http://127.0.0.1:6006"))
    ap.add_argument("--langs", default="en,ar")
    ap.add_argument("--review", default=str(ROOT / "reviews" / f"VOICE-E2E-{today}.md"))
    ap.add_argument("--no-review", action="store_true")
    args = ap.parse_args()
    if not shutil.which("say"):
        print("macOS `say` not found: this test makes its speech with it. Nothing was run.", file=sys.stderr)
        return 2
    if not (WEB / "node_modules").is_dir():
        print("web/node_modules missing: run `cd web && pnpm install` first.", file=sys.stderr)
        return 2
    runs: list[tuple[str, int, dict]] = []
    tmp = Path(tempfile.mkdtemp(prefix="fl-voice-e2e-"))
    try:
        for lang in [x.strip() for x in args.langs.split(",") if x.strip()]:
            wav = tmp / f"{lang}.wav"
            if not make_wav(lang, wav):
                runs.append(
                    (lang, 1, {"steps": [{"name": "speech", "status": "failed", "detail": "`say` voice missing"}]})
                )
                continue
            print(f"\n== {lang}: {args.base_url}")
            code, data = run_lang(lang, wav, args, tmp / f"{lang}.json")
            runs.append((lang, code, data))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not args.no_review:
        review(Path(args.review), args, runs)
    for lang, code, _ in runs:
        print(f"{lang}: {'passed' if code == 0 else 'FAILED'}")
    return 0 if runs and all(code == 0 for _, code, _ in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
