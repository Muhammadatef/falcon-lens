"""Generate the three verdict sound effects (earcons) in-repo, with numpy only: no third-party audio.

    uv run --project tools/voice_clips python tools/voice_clips/sfx.py --out web/public/voice/sfx

clear       calm two-note chime (C5 then G5), for "no warning signs found"
suspicious  soft two-tone caution (A4 then F#4, falling), for "suspicious"
dangerous   clear alert: three short beeps (A5), not a siren, for "dangerous"
Each is at most 700 ms, loudness -20 LUFS (quieter than the -16 LUFS voice clips), peak below -1 dBFS, mono mp3.
Licence: generated in this repository from sine waves; released under the repository licence, nothing is sampled.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent / "src"))
from voice_clips import audio  # noqa: E402

RATE = 24000
TARGET_LUFS = -20.0
MAX_MS = 700


def tone(freq: float, ms: int, decay: float = 7.0, harmonics: tuple[float, ...] = ()) -> audio.Wave:
    t = np.arange(int(RATE * ms / 1000)) / RATE
    x = np.sin(2 * np.pi * freq * t)
    for k, g in enumerate(harmonics, start=2):
        x = x + g * np.sin(2 * np.pi * freq * k * t)
    env = np.exp(-decay * t / (ms / 1000)) * np.minimum(1.0, t / 0.006)  # 6 ms attack, exponential decay
    return np.asarray(x * env, dtype=np.float32)


def gap(ms: int) -> audio.Wave:
    return np.zeros(int(RATE * ms / 1000), dtype=np.float32)


def build() -> dict[str, audio.Wave]:
    return {
        "clear": np.concatenate([tone(523.25, 200, 4.5), gap(30), tone(783.99, 260, 5.0)]),
        "suspicious": np.concatenate([tone(440.0, 190, 3.5, (0.25,)), gap(40), tone(369.99, 250, 3.5, (0.25,))]),
        "dangerous": np.concatenate([np.concatenate([tone(880.0, 110, 2.0, (0.0, 0.3)), gap(70)]) for _ in range(3)]),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    ext = audio.encoder_ext()
    manifest = []
    for name, wav in build().items():
        wav = audio.normalise_loudness(audio.fade(wav, RATE, 8), RATE, TARGET_LUFS)
        ms = audio.duration_ms(wav, RATE)
        if ms > MAX_MS:
            raise SystemExit(f"{name}: {ms} ms is longer than {MAX_MS} ms")
        audio.encode(wav, RATE, a.out / f"{name}.{ext}")
        manifest.append(
            {"id": f"sfx.{name}", "file": f"{name}.{ext}", "ms": ms, "lufs": round(audio.loudness_lufs(wav, RATE), 1)}
        )
        print(manifest[-1], flush=True)
    (a.out / "sfx.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (a.out / "LICENSE.txt").write_text(
        "Generated in this repository by tools/voice_clips/sfx.py from synthesised sine waves.\n"
        "No third-party audio is used. Released under the repository licence.\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
