# ruff: noqa: E501, S101, S603, S607
"""Sound for the hook film, built in code.

Three things are mixed on the cue sheet (`cues.py`):
- the Falcon's real voice clips (Amazon Polly "Zayd", pre-generated for the product) and the real verdict earcon,
  used as they are apart from level;
- the dialogue runs of the owner's footage, when the cut uses it;
- original music and effects synthesised below with numpy and scipy: sine, noise and additive voices only.
  No sample, no loop and no third-party recording is used, so there is nothing to license.

The music is in D minor and resolves to D major, the key of the bed already under the footage's dialogue, so the
joins are consonant. The master is limited below full scale and brought to the loudness target; `ffmpeg`'s
EBU R128 meter is the judge, not this file.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.ndimage import minimum_filter1d, uniform_filter1d

SR = 48_000
TARGET_LUFS = -14.4  # the brief: at or below -14 LUFS integrated
CEILING_DB = -2.0  # sample-peak ceiling of the master; leaves room for the AAC encoder's overshoot
Arr = np.ndarray[Any, np.dtype[np.float64]]

# Equal temperament, A4 = 440 Hz.
NOTE = {
    n: 440.0 * 2 ** ((i - 57) / 12)
    for i, n in enumerate(
        f"{p}{o}" for o in range(0, 8) for p in ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    )
}
D_MINOR = ("D2", "A2", "D3", "F3", "A3")
B_FLAT = ("A#1", "F2", "A#2", "D3", "F3")
D_MAJOR = ("D2", "A2", "D3", "F#3", "A3")


# ── small helpers ────────────────────────────────────────────────────────────────────────────────
def db(x: float) -> float:
    return float(10 ** (x / 20))


def _t(n: int) -> Arr:
    return np.arange(n, dtype=np.float64) / SR


def _sos(kind: str, fc: float | tuple[float, float], order: int = 4) -> Arr:
    return np.asarray(signal.butter(order, fc, btype=kind, fs=SR, output="sos"))


def _filt(x: Arr, sos: Arr) -> Arr:
    return np.asarray(signal.sosfilt(sos, x, axis=0))


def _noise(n: int, seed: int) -> Arr:
    return np.random.default_rng(seed).standard_normal(n)


def _fade(x: Arr, fin: float = 0.0, fout: float = 0.0) -> Arr:
    y = x.copy()
    a, b = int(fin * SR), int(fout * SR)
    if a > 1:
        ramp = 0.5 - 0.5 * np.cos(np.pi * np.arange(a) / a)
        y[:a] = (y[:a].T * ramp).T
    if b > 1:
        ramp = 0.5 + 0.5 * np.cos(np.pi * np.arange(b) / b)
        y[-b:] = (y[-b:].T * ramp).T
    return y


def _stereo(x: Arr, pan: float = 0.0) -> Arr:
    """Mono to stereo with an equal-power pan in [-1, 1]; stereo passes through."""
    if x.ndim == 2:
        return x
    a = (pan + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1) * np.sqrt(2) / np.sqrt(2)


def _place(bus: Arr, x: Arr, t0: float, gain: float = 1.0, pan: float = 0.0) -> None:
    s = _stereo(x, pan) * gain
    i = int(round(t0 * SR))
    if i < 0:
        s, i = s[-i:], 0
    j = min(len(bus), i + len(s))
    if j > i:
        bus[i:j] += s[: j - i]


def _sat(x: Arr, drive: float) -> Arr:
    return np.asarray(np.tanh(drive * x) / np.tanh(drive))


_IR_CACHE: dict[tuple[float, int], Arr] = {}


def _ir(rt60: float, seed: int) -> Arr:
    key = (rt60, seed)
    if key not in _IR_CACHE:
        n = int(SR * rt60 * 1.25)
        t = _t(n)
        chans = []
        for c in (0, 1):
            tail = _noise(n, seed + c) * np.exp(-6.91 * t / rt60)
            tail = _filt(_filt(tail, _sos("low", 5200, 2)), _sos("high", 220, 2))
            pre = int(0.014 * SR)
            tail = np.concatenate([np.zeros(pre), tail])[:n]
            chans.append(tail / np.sqrt(np.sum(tail**2)))
        _IR_CACHE[key] = np.stack(chans, axis=1)
    return _IR_CACHE[key]


def _reverb(x: Arr, rt60: float = 1.3, wet: float = 0.25, seed: int = 11) -> Arr:
    """Dry plus a diffuse tail (decaying filtered noise as the room)."""
    s = _stereo(x)
    ir = _ir(rt60, seed)
    out = np.zeros((len(s) + len(ir) - 1, 2))
    out[: len(s)] += s
    for c in (0, 1):
        out[:, c] += wet * signal.fftconvolve(s[:, c], ir[:, c])
    return out


# ── voices of the score ──────────────────────────────────────────────────────────────────────────
def taiko(f0: float = 70.0, dur: float = 1.5, hard: float = 1.0, seed: int = 1) -> Arr:
    """A big drum: the modes of a round skin with a falling pitch, a stick transient and a low slap."""
    n = int(dur * SR)
    t = _t(n)
    bend = 1.0 + 0.55 * hard * np.exp(-t / 0.028)
    phase = 2 * np.pi * np.cumsum(f0 * bend) / SR
    modes = (
        (1.00, 1.00, 0.42),
        (1.59, 0.50, 0.26),
        (2.14, 0.30, 0.18),
        (2.30, 0.22, 0.15),
        (2.65, 0.16, 0.11),
        (2.92, 0.12, 0.09),
        (3.16, 0.08, 0.07),
    )
    body = np.zeros(n)
    for i, (ratio, amp, tau) in enumerate(modes):
        body += amp * np.sin(ratio * phase + 0.7 * i) * np.exp(-t / tau)
    stick = _filt(_noise(n, seed), _sos("band", (700, 4200))) * np.exp(-t / 0.012) * 0.55 * hard
    slap = _filt(_noise(n, seed + 1), _sos("low", 900)) * np.exp(-t / 0.045) * 0.45
    x = _sat(body + stick + slap, 1.5)
    return np.asarray(x * np.minimum(1.0, t / 0.0015))


def boom(dur: float = 2.2, f_hi: float = 92.0, f_lo: float = NOTE["D1"], tau: float = 0.55) -> Arr:
    """Sub-bass hit: a sine that drops to D1."""
    n = int(dur * SR)
    t = _t(n)
    phase = 2 * np.pi * np.cumsum(f_lo + (f_hi - f_lo) * np.exp(-t / 0.075)) / SR
    x = np.sin(phase) * np.exp(-t / tau) + 0.25 * np.sin(2 * phase) * np.exp(-t / (tau * 0.45))
    click = _filt(_noise(n, 3), _sos("band", (1500, 5000))) * np.exp(-t / 0.004) * 0.25
    return np.asarray(_sat(x, 1.8) * np.minimum(1.0, t / 0.002) + click)


def brass(notes: tuple[str, ...], dur: float = 0.55, bright: float = 1.0) -> Arr:
    """A short brass-like chord: additive voices whose brightness opens with the attack, a small scoop into pitch."""
    n = int((dur + 0.4) * SR)
    t = _t(n)
    env = np.minimum(1.0, t / 0.022) * np.where(t < dur, 1.0 - 0.25 * t / dur, 0.75 * np.exp(-(t - dur) / 0.085))
    glow = np.clip((0.25 + 0.75 * np.exp(-t / 0.16)) * bright, 0.0, 1.0)
    scoop = 2 ** ((-35.0 * np.exp(-t / 0.018)) / 1200)
    out = np.zeros((n, 2))
    for name in notes:
        f = NOTE[name]
        for cents, pan in ((-7.0, -0.55), (0.0, 0.0), (6.0, 0.55)):
            ff = f * 2 ** (cents / 1200)
            ph = 2 * np.pi * np.cumsum(ff * scoop) / SR
            voice = np.zeros(n)
            for k in range(1, min(48, int(10_000 / ff)) + 1):
                voice += k ** -(0.8 + 1.5 * (1.0 - glow)) * np.sin(k * ph)
            out += _stereo(voice, pan) / 3
    out = (out.T * env).T / max(1, len(notes)) ** 0.5
    return _sat(out * 1.6, 1.3)


def spiccato(name: str, vel: float = 1.0, seed: int = 21) -> Arr:
    """One short low string stroke."""
    n = int(0.22 * SR)
    t = _t(n)
    f = NOTE[name]
    ph = 2 * np.pi * f * t
    x = np.zeros(n)
    for k in range(1, min(40, int(7000 / f)) + 1):
        x += np.sin(k * ph + 0.3 * k) / k
    x += 0.25 * _filt(_noise(n, seed), _sos("band", (1200, 5000))) * np.exp(-t / 0.01)
    x = _filt(x, _sos("low", 1500 + 1700 * vel, 2))
    return np.asarray(x * np.minimum(1.0, t / 0.004) * np.exp(-t / 0.05) * vel)


def sweep_noise(dur: float, f0: float, f1: float, power: float = 2.4, seed: int = 9, shape: str = "rise") -> Arr:
    """Noise seen through a moving band: a riser (`rise`) or a pass-by whoosh (`pass`)."""
    n = int(dur * SR)
    u = _t(n) / dur
    centre = f0 * (f1 / f0) ** (u**1.2)
    out = np.zeros((n, 2))
    for c in (0, 1):
        src = _noise(n, seed + c)
        for fc in np.geomspace(min(f0, f1) * 0.8, max(f0, f1) * 1.2, 12):
            band = _filt(src, _sos("band", (fc * 0.8, min(fc * 1.25, SR / 2 - 100)), 2))
            out[:, c] += band * np.exp(-0.5 * ((np.log2(fc) - np.log2(centre)) / 0.45) ** 2)
    gain = u**power if shape == "rise" else np.sin(np.pi * u) ** 2
    return _fade((out.T * gain).T, 0.0, 0.012)


def riser(dur: float = 1.25) -> Arr:
    n = int(dur * SR)
    t = _t(n)
    u = t / dur
    air = sweep_noise(dur, 300, 7000, 2.4, 9)
    f = NOTE["A2"] * (NOTE["D5"] / NOTE["A2"]) ** (u**1.6)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * u**2 * (0.6 + 0.4 * np.sin(2 * np.pi * np.cumsum(6 + 14 * u) / SR))
    return _fade(air * 0.8 + _stereo(tone) * 0.22, 0.0, 0.012)


def pad(
    notes: tuple[str, ...], dur: float, bright: float = 0.4, attack: float = 0.9, release: float = 1.4, seed: int = 31
) -> Arr:
    """A dark sustained chord: detuned additive voices, slow breathing, a little room."""
    n = int(dur * SR)
    t = _t(n)
    rng = np.random.default_rng(seed)
    out = np.zeros((n, 2))
    for name in notes:
        f = NOTE[name]
        for cents, pan in ((-5.0, -0.7), (4.0, 0.7), (0.0, 0.0)):
            ph = 2 * np.pi * f * 2 ** (cents / 1200) * t + rng.uniform(0, 6.28)
            voice = np.zeros(n)
            for k in range(1, min(14, int(2600 / f)) + 1):
                voice += np.sin(k * ph + rng.uniform(0, 6.28)) / k ** (2.3 - bright)
            breathe = 1 + 0.14 * np.sin(2 * np.pi * rng.uniform(0.07, 0.16) * t + rng.uniform(0, 6.28))
            out += _stereo(voice * breathe, pan)
    out = _filt(out, _sos("low", 900 + 1500 * bright, 2)) / (3 * len(notes)) ** 0.5
    return _reverb(_fade(out, attack, release), 1.6, 0.35, seed)[:n]


def thump(f_hi: float = 60.0, f_lo: float = 42.0, tau: float = 0.11) -> Arr:
    n = int(0.6 * SR)
    t = _t(n)
    ph = 2 * np.pi * np.cumsum(f_lo + (f_hi - f_lo) * np.exp(-t / 0.03)) / SR
    return np.asarray(np.sin(ph) * np.exp(-t / tau) * np.minimum(1.0, t / 0.003))


def blip(f: float, tau: float = 0.05, dur: float = 0.4, second: float = 0.3) -> Arr:
    """A soft sine note with a quick decay, the same family as the product's earcons."""
    n = int(dur * SR)
    t = _t(n)
    x = (np.sin(2 * np.pi * f * t) + second * np.sin(4 * np.pi * f * t)) * np.exp(-t / tau)
    return np.asarray(x * np.minimum(1.0, t / 0.004))


def tick(seed: int = 41, lo: float = 2500.0, hi: float = 7000.0) -> Arr:
    n = int(0.05 * SR)
    return np.asarray(_filt(_noise(n, seed), _sos("band", (lo, hi), 2)) * np.exp(-_t(n) / 0.006))


def buzz() -> Arr:
    """A phone vibrating on a table: two short bursts (no ringtone, nothing recognisable)."""
    n = int(0.62 * SR)
    t = _t(n)
    motor = _sat(np.sin(2 * np.pi * 162 * t), 4.0) * (1 + 0.35 * np.sin(2 * np.pi * 27 * t))
    rattle = _filt(_noise(n, 51), _sos("band", (1400, 3600), 2)) * (0.5 + 0.5 * np.sin(2 * np.pi * 162 * t)) * 0.18
    gate = ((t > 0.0) & (t < 0.22)) | ((t > 0.34) & (t < 0.58))
    env = uniform_filter1d(gate.astype(np.float64), int(0.012 * SR))
    return np.asarray(_filt(motor, _sos("band", (110, 700), 2)) * env * 0.8 + rattle * env)


def flutter(dur: float, seed: int = 61, rate: float = 34.0) -> Arr:
    """Quiet data chatter: many tiny ticks."""
    n = int(dur * SR)
    out = np.zeros((n, 2))
    rng = np.random.default_rng(seed)
    one = tick(seed, 3000, 8000)
    for k in range(int(dur * rate)):
        _place(out, one * rng.uniform(0.4, 1.0), (k + rng.uniform(0, 0.8)) / rate, 1.0, rng.uniform(-0.8, 0.8))
    return _fade(out, 0.08, 0.2)


def arp(dur: float, seed: int = 71) -> Arr:
    """A fast, quiet run of sine notes in D minor: the model thinking."""
    n = int(dur * SR)
    out = np.zeros((n, 2))
    rng = np.random.default_rng(seed)
    scale = ("D5", "F5", "G5", "A5", "C6", "D6", "F6", "A6")
    step = 0.085
    for k in range(int(dur / step)):
        name = scale[(k * 3 + int(rng.integers(0, 2))) % len(scale)]
        _place(out, blip(NOTE[name], 0.06, 0.3, 0.15), k * step, 0.5 + 0.5 * k * step / dur, rng.uniform(-0.7, 0.7))
    return _reverb(_fade(out, 0.05, 0.25), 1.1, 0.4, seed)[:n]


# ── the score ────────────────────────────────────────────────────────────────────────────────────
def _scene(tl: dict[str, Any], sid: str) -> tuple[float, float] | None:
    for s in tl["scenes"]:
        if s["id"] == sid:
            return float(s["t0"]), float(s["t1"])
    return None


def _line(tl: dict[str, Any], lid: str) -> dict[str, Any] | None:
    return next((ln for ln in tl["lines"] if ln["id"] == lid), None)


def score(tl: dict[str, Any]) -> tuple[Arr, Arr, Arr]:
    """Music and effects for one cut, as three stereo buses: the sting (logo hits), the bed, the effects."""
    n = int(round(tl["duration"] * SR)) + SR
    music = np.zeros((n, 2))  # the sting
    bed = np.zeros((n, 2))
    sfx = np.zeros((n, 2))
    m = tl["marks"]
    variant = tl["variant"]

    # Logo sting: rumble and riser, string strokes, two drum hits and a fill, brass on the wordmark.
    beat = m["intro.hit2"] - m["intro.tap1"]  # one beat of the 140 bpm grid
    _place(music, _fade(_stereo(np.sin(2 * np.pi * NOTE["D1"] * _t(int(1.3 * SR)))), 0.9, 0.05), 0.0, db(-16))
    _place(music, riser(m["intro.hit1"] - 0.06), 0.04, db(-11))
    sixteenth = beat / 4
    strokes = int((m["intro.hit1"] - beat) / sixteenth)
    for k in range(strokes):
        vel = 0.35 + 0.65 * (k + 1) / strokes
        at = m["intro.hit1"] - (strokes - k) * sixteenth
        _place(music, spiccato("D2" if k % 4 else "D3", vel, 21 + k), at, db(-13), -0.25 if k % 2 else 0.25)
    hall = lambda x, wet=0.3: _reverb(x, 1.5, wet, 13)  # noqa: E731
    _place(music, hall(taiko(66, 1.6, 1.0, 1)), m["intro.hit1"], db(-4.5))
    _place(music, boom(2.0), m["intro.hit1"], db(-7))
    _place(music, hall(taiko(84, 1.0, 0.7, 4)), m["intro.tap1"], db(-10), -0.3)
    _place(music, hall(taiko(98, 0.9, 0.8, 6)), m["intro.tap2"], db(-8.5), 0.3)
    _place(music, hall(taiko(60, 1.8, 1.0, 8)), m["intro.hit2"], db(-3.5))
    _place(music, boom(2.4, 100.0), m["intro.hit2"], db(-5.5))
    _place(music, hall(brass(("D2", "A2", "D3", "F3", "A3", "D4"), 0.5), 0.4), m["intro.hit2"], db(-8))
    _place(music, hall(_fade(sweep_noise(0.9, 9000, 2500, 1.0, 15, "pass"), 0.0, 0.5), 0.5), m["intro.hit2"], db(-24))
    if variant == "intro":
        return music, bed, sfx
    _place(sfx, sweep_noise(tl["scenes"][1]["t0"] - m["intro.out"], 500, 6000, 2.0, 17), m["intro.out"], db(-17))

    # Cold open: the phone buzzes, the message lands, a low note holds the tension.
    _place(sfx, buzz(), m["cold.buzz"], db(-21))
    _place(sfx, thump(150, 70, 0.05), m["cold.land"], db(-12))
    _place(sfx, sweep_noise(0.3, 5000, 900, 1.0, 19, "pass"), m["cold.land"] - 0.14, db(-22))
    cold = _scene(tl, "cold")
    wake = _scene(tl, "wake")
    assert cold and wake
    if variant == "sequence":
        hold = wake[0] + 0.6 - cold[0]
        _place(bed, pad(("D2", "A2", "D3"), hold, 0.25, 1.2, 0.5, 33), cold[0], db(-20))
        thin = np.sin(2 * np.pi * NOTE["A5"] * _t(int((m["cold.stop"] - m["cold.urgent"]) * SR)))
        _place(bed, _fade(_stereo(thin), 1.6, 0.06), m["cold.urgent"], db(-36))
        for name in ("cold.beat1", "cold.beat2"):
            _place(sfx, thump(), m[name], db(-11))
            _place(sfx, thump(54, 40, 0.09), m[name] + 0.27, db(-15))
        _place(sfx, sweep_noise(0.25, 800, 4000, 1.6, 23), m["cold.stop"] - 0.25, db(-24))
    else:
        for name in ("cold.beat1", "cold.beat2"):
            _place(sfx, thump(), m[name], db(-14))
            _place(sfx, thump(54, 40, 0.09), m[name] + 0.27, db(-18))

    # The Falcon wakes: two rising sine notes, then a calm bed in D minor under the checks.
    _place(sfx, _reverb(blip(NOTE["A4"], 0.11, 0.5), 1.0, 0.3, 25), m["wake.chime"], db(-19))
    _place(sfx, _reverb(blip(NOTE["D5"], 0.16, 0.7), 1.0, 0.3, 26), m["wake.chime"] + 0.11, db(-18))
    _place(sfx, sweep_noise(0.35, 700, 5200, 1.8, 27), m["wake.snap"] - 0.3, db(-21))
    verdict = _scene(tl, "verdict")
    ai = _scene(tl, "ai")
    todo = _scene(tl, "todo")
    assert verdict and ai and todo
    bed0 = wake[0] + 0.25
    _place(bed, pad(D_MINOR, ai[0] - bed0 + 1.0, 0.35, 1.0, 1.2, 35), bed0, db(-23))
    period = 60.0 / 70.0
    k = 0
    while bed0 + 0.4 + k * period < m["verdict.converge"] - 0.2:
        _place(bed, thump(58, 44, 0.1), bed0 + 0.4 + k * period, db(-18))
        k += 1
    # B flat under the last check, a riser into the verdict, then silence for the earcon.
    _place(bed, pad(B_FLAT, m["verdict.slam"] - ai[0] + 0.1, 0.5, 0.9, 0.12, 37), ai[0] - 0.1, db(-22))
    _place(sfx, riser(m["verdict.slam"] - m["verdict.converge"] - 0.05), m["verdict.converge"], db(-16))

    def at(sid: str) -> float:
        s = _scene(tl, sid)
        assert s
        return s[0]

    # One small sound per step, so the picture's moves are heard without crowding the voice.
    for sid in ("found", "baseer", "lists", "address", "page", "ai"):
        _place(sfx, sweep_noise(0.28, 900, 3600, 1.4, 81, "pass"), at(sid) - 0.05, db(-27))
    for ln in tl["lines"]:
        if (
            ln["who"] == "falcon"
            and ln["step"]
            and ln["scene"] in ("found", "baseer", "lists", "address", "page", "ai")
        ):
            _place(sfx, blip(NOTE["A5"], 0.03, 0.15, 0.1), ln["t1"] + 0.02, db(-29), 0.2)  # the step's tick
    _place(sfx, tick(43), at("found") + 0.3, db(-22), -0.2)
    _place(sfx, tick(44), at("found") + 0.42, db(-22), 0.2)
    lists = _scene(tl, "lists")
    assert lists
    _place(sfx, flutter(lists[1] - lists[0] - 0.3), lists[0] + 0.25, db(-20))
    address = _scene(tl, "address")
    assert address
    _place(sfx, thump(120, 80, 0.05), address[0] + 1.75, db(-20))
    page = _scene(tl, "page")
    assert page
    _place(sfx, sweep_noise(0.7, 300, 1800, 1.0, 83, "pass"), page[0] + 0.1, db(-24))
    for dt in (2.15, 2.75):
        _place(sfx, blip(NOTE["F5"], 0.04, 0.2, 0.2), page[0] + dt, db(-25), -0.3)
    _place(sfx, arp(ai[1] - ai[0] - 0.4), ai[0] + 0.3, db(-27))

    # Dir: sonar pings as the similar reports appear, a soft link when the campaign closes.
    dirs = _scene(tl, "dir")
    assert dirs
    _place(bed, pad(D_MINOR, todo[0] - dirs[0] + 0.8, 0.3, 0.6, 1.0, 39), dirs[0], db(-23))
    ping = _reverb(blip(NOTE["E6"], 0.16, 0.9, 0.05), 1.4, 0.5, 29)
    _place(sfx, ping, m["dir.ping1"], db(-24), -0.4)
    _place(sfx, ping, m["dir.ping2"], db(-24), 0.4)
    _place(sfx, _reverb(blip(NOTE["A5"], 0.2, 0.9, 0.2), 1.4, 0.45, 30), m["dir.link"], db(-21))

    # Advice and close: D major, then a softer echo of the sting on the end card.
    end = _scene(tl, "end")
    assert end
    _place(bed, pad(D_MAJOR, tl["duration"] - todo[0] + 0.2, 0.45, 1.0, 1.6, 41), todo[0] - 0.1, db(-22))
    for ln in tl["lines"]:
        if ln["id"] in ("todo.link", "todo.otp"):
            _place(sfx, blip(NOTE["D6"], 0.05, 0.25, 0.1), ln["t0"] + 0.02, db(-27))
    _place(music, hall(taiko(66, 1.6, 0.8, 91), 0.35), m["end.hit"], db(-8))
    _place(music, boom(2.0, 80.0), m["end.hit"], db(-10))
    _place(music, hall(brass(("D2", "A2", "D3", "F#3", "A3", "D4"), 0.7, 0.75), 0.45), m["end.hit"], db(-10))
    _place(sfx, sweep_noise(0.45, 700, 5000, 1.8, 93), m["end.hit"] - 0.45, db(-22))
    return music, bed, sfx


# ── the real clips and the footage ───────────────────────────────────────────────────────────────
def decode(path: Path, start: float | None = None, end: float | None = None, mono: bool = False) -> Arr:
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    if end is not None:
        cmd += ["-to", f"{end:.4f}"]
    cmd += ["-i", str(path), "-vn", "-f", "f32le", "-ac", "1" if mono else "2", "-ar", str(SR), "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    x = np.frombuffer(raw, dtype=np.float32).astype(np.float64)
    return x if mono else x.reshape(-1, 2)


def clip_seconds(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return float(out.strip())


VOICE_RMS_DB = -14.5  # every clip is brought to this level (mono RMS); nothing else about a clip is changed
VOICE_TRIM_DB = 4.0  # ... by at most this much


def voice_buses(tl: dict[str, Any], clips_dir: Path, sfx_dir: Path) -> tuple[Arr, Arr]:
    """The Falcon's clips and the verdict earcon, placed on the cue sheet. Level only; nothing else is changed."""
    n = int(round(tl["duration"] * SR)) + SR
    voice = np.zeros((n, 2))
    earcon = np.zeros((n, 2))
    for c in tl["clips"]:
        if c["kind"] == "voice":
            x = decode(clips_dir / c["file"], mono=True)
            level = 20 * np.log10(np.sqrt(np.mean(x**2)) + 1e-12)
            gain = float(np.clip(VOICE_RMS_DB - level, -VOICE_TRIM_DB, VOICE_TRIM_DB))
            _place(voice, x, c["t0"], db(gain))
        else:
            _place(earcon, decode(sfx_dir / c["file"], mono=True), c["t0"], db(+9.0))
    return voice, earcon


LIVE_GAIN_DB = 1.5  # brings the footage's dialogue to the level of the Falcon's clips


def live_bus(tl: dict[str, Any], footage: Path | None) -> Arr:
    n = int(round(tl["duration"] * SR)) + SR
    bus = np.zeros((n, 2))
    if footage is None:
        return bus
    lead = 0.03
    for run in tl["live_audio"]:
        x = decode(footage, run["src0"] - lead, run["src1"] + lead)
        _place(bus, _fade(x, 2 * lead, 2 * lead), run["t0"] - lead, db(LIVE_GAIN_DB))
    return bus


# ── envelopes the page animates to ───────────────────────────────────────────────────────────────
def _frame_rms(x: Arr, fps: int, frames: int) -> Arr:
    hop = SR // fps
    mono = x.mean(axis=1) if x.ndim == 2 else x
    mono = np.concatenate([mono, np.zeros(max(0, frames * hop - len(mono)))])[: frames * hop]
    return np.asarray(np.sqrt((mono.reshape(frames, hop) ** 2).mean(axis=1)))


def _norm(v: Arr, pct: float = 97.0) -> Arr:
    top = np.percentile(v[v > 1e-5], pct) if np.any(v > 1e-5) else 1.0
    return np.clip(v / max(top, 1e-9), 0.0, 1.0)


def envelopes(tl: dict[str, Any], stems: dict[str, Arr]) -> dict[str, Any]:
    """Per-frame levels: the speaking voice (and eight bands of it), the actor's voice, the music and its low end."""
    fps, frames = tl["fps"], tl["frames"]
    speech = _filt(stems["live"].mean(axis=1), _sos("band", (300, 6000), 2))
    falcon = stems["voice"].mean(axis=1)
    bands = []
    edges = np.geomspace(160, 6400, 9)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        bands.append(_norm(_frame_rms(_filt(falcon + speech, _sos("band", (lo, hi), 2)), fps, frames), 99.0))
    low = _filt(stems["music"].mean(axis=1), _sos("low", 140, 2))  # the sting only: the picture pulses on its hits
    out = {
        "voice": _norm(_frame_rms(falcon, fps, frames)),
        "live": _norm(_frame_rms(speech, fps, frames)),
        "music": _norm(_frame_rms(stems["music"], fps, frames), 99.5),
        "low": _norm(_frame_rms(low, fps, frames), 99.5),
        "bands": bands,
    }
    return {
        k: ([[round(float(x), 3) for x in b] for b in v] if k == "bands" else [round(float(x), 3) for x in v])
        for k, v in out.items()
    }


# ── mix and master ───────────────────────────────────────────────────────────────────────────────
def _follow(x: Arr, attack: float, release: float) -> Arr:
    """Peak follower on a mono signal (for ducking)."""
    level = np.abs(x)
    hop = 64
    blocks = level[: len(level) // hop * hop].reshape(-1, hop).max(axis=1)
    out = np.zeros_like(blocks)
    a, r = np.exp(-hop / (attack * SR)), np.exp(-hop / (release * SR))
    y = 0.0
    for i, v in enumerate(blocks):
        y = a * y + (1 - a) * v if v > y else r * y + (1 - r) * v
        out[i] = y
    return np.asarray(np.repeat(out, hop))


STING_DB = -3.5  # logo hits against the voice
BED_DB = 2.0
SFX_DB = 6.0


def mix(tl: dict[str, Any], stems: dict[str, Arr]) -> Arr:
    n = int(round(tl["duration"] * SR))
    talk = stems["voice"].mean(axis=1) + stems["live"].mean(axis=1) + stems["earcon"].mean(axis=1)
    env = _follow(talk, 0.02, 0.35)
    env = np.concatenate([env, np.zeros(max(0, len(talk) - len(env)))])[: len(talk)]
    duck = 1.0 - 0.62 * np.clip(env / 0.2, 0.0, 1.0)  # the bed steps back under speech
    quiet = np.ones(len(talk))  # and goes silent around the earcon, so it lands clean
    slam = tl["marks"].get("verdict.slam")
    if slam is not None:
        a, b = int((slam - 0.07) * SR), int((slam + 0.62) * SR)
        quiet[a:b] = 0.0
        quiet = uniform_filter1d(quiet, int(0.05 * SR))
    knee = db(-1.0)
    sting = knee * np.tanh(
        stems["music"] * db(STING_DB) / knee
    )  # round the drum peaks instead of leaning on the limiter
    bed = (stems["bed"].T * duck * quiet).T * db(BED_DB)
    sfx = (stems["sfx"].T * (0.55 + 0.45 * duck) * quiet).T * db(SFX_DB)
    out = stems["voice"] + stems["earcon"] + stems["live"] + sting + bed + sfx
    out = _filt(out[:n], _sos("high", 28, 2))
    if tl["variant"] == "intro":
        out = _fade(out, 0.0, 0.35)
    return _fade(out, 0.0, 0.06)


def limit(x: Arr, ceiling_db: float = CEILING_DB, look: float = 0.004) -> Arr:
    """Look-ahead peak limiter. Detection runs on a 4x oversampled copy, so peaks between samples are caught too."""
    ceiling = db(ceiling_db)
    over = signal.resample_poly(x, 4, 1, axis=0)
    peak = np.abs(over).max(axis=1).reshape(-1, 4).max(axis=1)
    need = np.minimum(1.0, ceiling / np.maximum(peak, 1e-9))
    win = int(look * SR) | 1
    gain = uniform_filter1d(minimum_filter1d(need, 2 * win + 1), win)
    return (x.T * gain).T


def measure(path: Path) -> dict[str, float]:
    """Integrated loudness, loudness range and true peak, read from ffmpeg's EBU R128 meter."""
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0", "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    ).stderr  # fmt: skip
    tail = err[err.rfind("Summary:") :]
    grab = lambda label: float(re.search(rf"{label}:\s+(-?[\d.]+)", tail).group(1))  # type: ignore[union-attr]  # noqa: E731
    return {"lufs": grab("I"), "lra": grab("LRA"), "true_peak": grab("Peak")}


def write_wav(path: Path, x: Arr) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), SR, x.astype(np.float32))


def master(x: Arr, path: Path, target: float = TARGET_LUFS) -> dict[str, float]:
    """Limit, then trim the gain until the meter reads the target. Returns the final reading."""
    gain = 1.0
    reading: dict[str, float] = {}
    for _ in range(6):
        y = limit(x * gain)
        write_wav(path, y)
        reading = measure(path)
        if abs(reading["lufs"] - target) < 0.08:
            break
        gain *= db(target - reading["lufs"])
    return reading


def build(tl: dict[str, Any], out_dir: Path, clips_dir: Path, sfx_dir: Path, footage: Path | None) -> dict[str, Any]:
    """Write the stems and the master for one cut; return the meter reading and the envelopes for the page."""
    music, bed, sfx = score(tl)
    voice, earcon = voice_buses(tl, clips_dir, sfx_dir)
    stems = {"music": music, "bed": bed, "sfx": sfx, "voice": voice, "earcon": earcon, "live": live_bus(tl, footage)}
    n = int(round(tl["duration"] * SR))
    for name, bus in stems.items():
        write_wav(out_dir / f"stem_{name}.wav", bus[:n])
    reading = master(mix(tl, stems), out_dir / "master.wav")
    return {"reading": reading, "env": envelopes(tl, stems)}
