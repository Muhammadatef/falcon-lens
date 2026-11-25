# ruff: noqa: E501, S603, S607
"""Word timings for the Falcon's clips, so each caption word lights up when it is spoken.

Uses a local speech recogniser when one is installed (`mlx_whisper`, the engine `make voice-native` uses) and maps
its word times onto the script's own words; the caption text itself always comes from the cue sheet. Without the
tool the caller falls back to spreading the words evenly, which is close for these short, evenly paced clips.
Nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

MODEL = "mlx-community/whisper-small-mlx"


def _letters(word: str) -> int:
    return max(1, len(re.sub(r"[^\w]", "", word)))


def heard_words(clip: Path) -> list[tuple[float, float, str]] | None:
    """(start, end, word) for each word the recogniser hears, or None when it is not available."""
    tool = shutil.which("mlx_whisper")
    if tool is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [tool, str(clip), "--model", MODEL, "--language", "ar", "--word-timestamps", "True",
               "--output-format", "json", "--output-dir", tmp, "--output-name", "clip", "--verbose", "False"]  # fmt: skip
        done = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "HF_HUB_OFFLINE": "1"})
        out = Path(tmp) / "clip.json"
        if done.returncode != 0 or not out.exists():
            return None
        data = json.loads(out.read_text())
    words = [
        (float(w["start"]), float(w["end"]), str(w["word"]).strip())
        for seg in data.get("segments", [])
        for w in seg.get("words", [])
    ]
    return words or None


def align(text: str, heard: list[tuple[float, float, str]], length: float) -> list[list[Any]]:
    """Start time of each script word: the moment the recogniser had heard the same share of the letters."""
    script = [w for w in text.split() if w]
    total = sum(_letters(w) for w in script)
    spans: list[tuple[float, float, int]] = [(a, b, _letters(w)) for a, b, w in heard]
    heard_total = sum(n for _, _, n in spans)
    out: list[list[Any]] = []
    seen = 0
    for word in script:
        target = seen / total * heard_total
        acc = 0.0
        when = spans[-1][1]
        for a, b, n in spans:
            if acc + n > target:
                when = a + (b - a) * (target - acc) / n
                break
            acc += n
        out.append([word, round(min(max(when, 0.0), max(0.0, length - 0.05)), 3)])
        seen += _letters(word)
    for i in range(1, len(out)):  # never out of order
        out[i][1] = max(out[i][1], out[i - 1][1] + 0.04)
    return out


def align_clips(clips: dict[str, tuple[Path, str, float]]) -> dict[str, list[list[Any]]]:
    """key -> [[word, seconds from the start of the clip], ...] for every clip the recogniser could read."""
    out: dict[str, list[list[Any]]] = {}
    for key, (path, text, length) in clips.items():
        heard = heard_words(path)
        if heard:
            out[key] = align(text, heard, length)
    return out
