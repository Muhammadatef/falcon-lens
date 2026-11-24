"""The generated verdict earcons: short, quiet, distinct, committed."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sfx", ROOT / "sfx.py")
assert spec and spec.loader
sfx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sfx)
from voice_clips import audio  # noqa: E402


def test_each_effect_is_short_quiet_and_distinct() -> None:
    waves = sfx.build()
    assert set(waves) == {"clear", "suspicious", "dangerous"}
    seen = set()
    for name, w in waves.items():
        w = audio.normalise_loudness(audio.fade(w, sfx.RATE, 8), sfx.RATE, sfx.TARGET_LUFS)
        assert audio.duration_ms(w, sfx.RATE) <= 700, name
        assert audio.loudness_lufs(w, sfx.RATE) <= -18.0, name
        assert float(np.max(np.abs(w))) <= 0.9, name
        seen.add(round(float(np.sum(np.abs(np.diff(np.sign(w))))), -1))
    assert len(seen) == 3


def test_committed_files_match_the_manifest() -> None:
    out = ROOT.parents[1] / "web" / "public" / "voice" / "sfx"
    manifest = json.loads((out / "sfx.json").read_text("utf-8"))
    assert [m["id"] for m in manifest] == ["sfx.clear", "sfx.suspicious", "sfx.dangerous"]
    for m in manifest:
        assert (out / m["file"]).stat().st_size > 500
        assert m["ms"] <= 700 and m["lufs"] <= -18.0
    assert "Generated in this repository" in (out / "LICENSE.txt").read_text("utf-8")
