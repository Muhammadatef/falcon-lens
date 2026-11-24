"""Audio post-processing: mono, resample, trim, LUFS-normalise, fade, encode."""

from __future__ import annotations

import shutil
import subprocess
from math import gcd
from pathlib import Path

import numpy as np
import numpy.typing as npt
import soundfile as sf
from scipy.signal import lfilter, resample_poly

Wave = npt.NDArray[np.float32]

TARGET_LUFS = -16.0
CEILING = 10 ** (-1.0 / 20)  # -1 dBFS sample-peak ceiling
FADE_MS = 40
DEFAULT_RATE = 24000


def to_mono(x: npt.ArrayLike) -> Wave:
    a = np.asarray(x, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=-1 if a.shape[-1] <= 8 else 0)
    return np.asarray(a, dtype=np.float32)


def resample(x: Wave, src: int, dst: int) -> Wave:
    if src == dst:
        return x
    g = gcd(src, dst)
    return np.asarray(resample_poly(x, dst // g, src // g), dtype=np.float32)


def trim_silence(x: Wave, rate: int, thresh_db: float = -45.0, pad_ms: int = 30) -> Wave:
    """Cut leading/trailing samples quieter than thresh_db (keeps a small pad)."""
    if x.size == 0:
        return x
    idx = np.flatnonzero(np.abs(x) > 10 ** (thresh_db / 20))
    if idx.size == 0:
        return x
    pad = int(rate * pad_ms / 1000)
    return x[max(0, int(idx[0]) - pad) : min(x.size, int(idx[-1]) + 1 + pad)]


def fade(x: Wave, rate: int, ms: int = FADE_MS) -> Wave:
    n = min(int(rate * ms / 1000), x.size // 2)
    if n <= 0:
        return x
    out = x.copy()
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
    out[:n] *= ramp
    out[-n:] *= ramp[::-1]
    return out


def loudness_lufs(x: Wave, rate: int) -> float:
    """Integrated loudness (ITU-R BS.1770-4: K-weighting, 400 ms blocks, two gates)."""
    y = resample(x, rate, 48000)
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]
    a1 = [1.0, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]
    a2 = [1.0, -1.99004745483398, 0.99007225036621]
    z = lfilter(b2, a2, lfilter(b1, a1, y))
    block, step = 19200, 4800
    if z.size < block:
        ms = float(np.mean(z**2))
        return float(-0.691 + 10 * np.log10(ms)) if ms > 0 else -120.0
    powers = np.array([np.mean(z[i : i + block] ** 2) for i in range(0, z.size - block + 1, step)])
    loud = -0.691 + 10 * np.log10(np.maximum(powers, 1e-12))
    kept = powers[loud > -70.0]
    if kept.size == 0:
        return -120.0
    rel = -0.691 + 10 * np.log10(kept.mean()) - 10.0
    kept = kept[-0.691 + 10 * np.log10(np.maximum(kept, 1e-12)) > rel]
    return float(-0.691 + 10 * np.log10(kept.mean())) if kept.size else -120.0


def normalise_loudness(x: Wave, rate: int, target: float = TARGET_LUFS) -> Wave:
    cur = loudness_lufs(x, rate)
    if cur <= -100:
        return x
    y = x * np.float32(10 ** ((target - cur) / 20))
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > CEILING:  # scale down rather than clip
        y = y * np.float32(CEILING / peak)
    return np.asarray(y, dtype=np.float32)


def process(x: npt.ArrayLike, src_rate: int, out_rate: int = DEFAULT_RATE) -> Wave:
    """Full chain: mono -> resample -> trim -> loudness -> fades."""
    y = resample(to_mono(x), src_rate, out_rate)
    y = trim_silence(y, out_rate)
    y = normalise_loudness(y, out_rate)
    return fade(y, out_rate)


def encoder_ext() -> str:
    """mp3 when ffmpeg has libmp3lame, else ogg (libvorbis), else raises."""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found")
    enc = subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    if "libmp3lame" in enc:
        return "mp3"
    if "libvorbis" in enc:
        return "ogg"
    raise RuntimeError("ffmpeg has neither libmp3lame nor libvorbis")


def encode(x: Wave, rate: int, path: Path) -> None:
    """Write x to path (.mp3 / .ogg) through ffmpeg; mono."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wav = path.with_suffix(".tmp.wav")
    sf.write(str(wav), x, rate, subtype="PCM_16")
    codec = ["-c:a", "libmp3lame", "-b:a", "64k"] if path.suffix == ".mp3" else ["-c:a", "libvorbis", "-q:a", "3"]
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-ac", "1", *codec, str(path)],
            check=True,
        )
    finally:
        wav.unlink(missing_ok=True)


def duration_ms(x: Wave, rate: int) -> int:
    return int(round(1000 * x.size / rate))
