"""Deterministic guards against Whisper repetition loops and echoed prompts.

Adapted from the owner's Neo project (stt_guard.py / stt_lang.py), generic logic only.
  collapse_repeats: any 1-6 word n-gram repeated more than ``max_rep`` times back to back is kept
      ``max_rep`` times (AR + EN; the compare ignores case, punctuation, Arabic diacritics, tatweel).
      N-grams holding a digit are never collapsed.
  word_cap: the most words a clip of ``audio_s`` seconds can plausibly hold.
  echo_guard: drop the transcript when Whisper looped (segment compression_ratio above 2.4).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping

MAX_N = 6
# Decoding prompt, per language (a mixed prompt is echoed on English audio and on noise). It DESCRIBES the product
# and never ends on, or consists of, the wake phrase. Measured on the shipped model with synthetic speech
# (reviews/AUDIT-VOICE-20261124-1905.md, 52 bench clips + 8 extra):
#   "Hey Falcon. Falcon Lens." (the old prompt): a spoken "Falcon Lens, check what I copied" came back as
#       "Check what I copied." (Whisper took the name for the prompt continuing), and silence/noise came back as
#       the wake phrase itself.
#   "Glossary: Falcon Lens, Hey Falcon, clipboard.": kept "Falcon Lens" but dropped one leading "Hey Falcon".
#   no prompt: «يا صقر» became «يا سقرن» / "Hey Falk" on some clips (5 misses).
#   this prompt: no leading name dropped, the product spelling kept, and non-speech came back as stock phrases
#       ("The", «ترجمة نانسي قنقر») that contain no wake word.
PROMPTS = {
    "en": "Falcon Lens is an assistant; people call it Falcon. It checks copied messages for scams.",
    "ar": "عدسة الصقر مساعد، ويناديه الناس صقر. يفحص الرسائل المنسوخة ويكشف الاحتيال.",
}
COMPRESSION_MAX = 2.4
_DIACRITICS = re.compile("[ً-ٰٟـ]")
_DIGIT = re.compile("[0-9٠-٩۰-۹]")


def _key(word: str) -> str:
    w = _DIACRITICS.sub("", word.lower())
    return "".join(ch for ch in w if not unicodedata.category(ch).startswith("P"))


def _run_length(keys: list[str], i: int, n: int) -> int:
    gram = keys[i : i + n]
    count = 1
    j = i + n
    while keys[j : j + n] == gram:
        count += 1
        j += n
    return count


def _collapse_at(keys: list[str], i: int, max_rep: int) -> tuple[int, int] | None:
    for n in range(1, min(MAX_N, len(keys) - i) + 1):
        gram = keys[i : i + n]
        if not any(gram) or any(_DIGIT.search(k) for k in gram):
            continue
        count = _run_length(keys, i, n)
        if count > max_rep:
            return n, count
    return None


def collapse_repeats(text: str, max_rep: int = 2) -> str:
    words = text.split()
    keys = [_key(w) for w in words]
    out: list[str] = []
    i = 0
    while i < len(words):
        skip = _collapse_at(keys, i, max_rep)
        if skip:
            n, count = skip
            out.extend(words[i : i + max_rep * n])
            i += count * n
        else:
            out.append(words[i])
            i += 1
    return " ".join(out)


def word_cap(audio_s: float) -> int:
    return max(8, math.ceil(audio_s * 4.5))


def cap_words(text: str, n: int) -> str:
    return " ".join(text.split()[: max(n, 0)])


def echo_guard(text: str, segments: Iterable[Mapping[str, object]]) -> str:
    for s in segments:
        ratio = s.get("compression_ratio", 0) or 0
        if isinstance(ratio, int | float) and ratio > COMPRESSION_MAX:
            return ""
    return text


# Whisper invents stock phrases on silence or noise (measured on the shipped model: "Thank you." and
# «ترجمة نانسي قنقر» without a prompt). None of them is ever a command, so they are dropped.
_HALLUCINATIONS = re.compile(
    r"(thanks? (you )?for watching\.?|thank you( very much)?\.?|you\.?|bye\.?|\.+|شكرا\.?|شكرا للمشاهده\.?"
    r"|ترجمه نانسي قنقر\.?|اشتركوا في القناه\.?|لا تنسوا الاشتراك في القناه\.?"
    r"|the end\.?|the\.?)",
    re.IGNORECASE,
)
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})

# Wake words. A person says ONE wake phrase, so a transcript made only of these words that holds more than one
# phrase (4+ words, or both scripts) is Whisper repeating itself, not speech. (With the previous prompt, pink noise
# came back as «عدسة الصقر. هاي فالكون.».)
_WAKE_WORDS = frozenset({"hey", "falcon", "lens", "يا", "صقر", "عدسه", "الصقر", "هاي", "فالكون", "لينس", "لنس"})
PROMPT_ECHO_MIN_WORDS = 4


def _fold(text: str) -> str:
    return _DIACRITICS.sub("", text.lower()).translate(_FOLD)


def _words(text: str) -> list[str]:
    return [k for k in (_key(w).translate(_FOLD) for w in text.split()) if k]


_PROMPT_RUNS = tuple(" " + " ".join(_words(p)) + " " for p in PROMPTS.values())


def is_prompt_echo(text: str) -> bool:
    """True when the transcript is the decoding prompt read back: a run of 4+ words of it, or only wake phrases."""
    words = _words(text)
    if len(words) >= PROMPT_ECHO_MIN_WORDS and any(f" {' '.join(words)} " in run for run in _PROMPT_RUNS):
        return True
    if not words or any(w not in _WAKE_WORDS for w in words):
        return False
    mixed = any(w.isascii() for w in words) and any(not w.isascii() for w in words)
    return mixed or len(words) >= PROMPT_ECHO_MIN_WORDS


# --- signal gate (before Whisper) ----------------------------------------------------------------------
# Speech is bursty: syllables and pauses make the loudest 20 ms frames many times louder than the quietest.
# Silence, a fan, a tone or steady crowd noise are flat. Measured on 16 kHz clips (p95 / p10 of 20 ms frame RMS):
# silence 0, pink noise 1.7, white noise 1.1, a tone 1.0; speech 12-150 clean, 4.1-5.0 at 10 dB SNR, 2.9-3.3 at
# 6 dB. Flat audio never reaches Whisper, so it cannot echo the prompt into a false wake.
FRAME_S = 0.02
MIN_PEAK_RMS = 0.003  # about -50 dBFS: below this the loudest frames are still silence
MIN_SPREAD = 2.5
VOICED_FRACTION = 0.3  # a frame counts as voiced when it is at least this share of the loud (p95) level
SPARSE_MAX_WORDS = 3
SPARSE_MIN_VOICED_S = 2.5


def _percentile(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def frame_stats(frame_rms: Iterable[float]) -> tuple[float, float, float]:
    """(loud level p95, spread p95/p10, seconds of voiced frames) from per-frame RMS values (FRAME_S frames)."""
    vals = [float(v) for v in frame_rms]
    if not vals:
        return 0.0, 0.0, 0.0
    ordered = sorted(vals)
    p95, p10 = _percentile(ordered, 0.95), _percentile(ordered, 0.10)
    voiced = sum(1 for v in vals if v >= VOICED_FRACTION * p95) if p95 > 0 else 0
    return p95, p95 / max(p10, 1e-6), voiced * FRAME_S


def speech_like(frame_rms: Iterable[float]) -> bool:
    """False for silence and for flat audio (steady noise, tones): such a clip is answered with an empty transcript."""
    p95, spread, _ = frame_stats(frame_rms)
    return p95 >= MIN_PEAK_RMS and spread >= MIN_SPREAD


def is_sparse(text: str, voiced_s: float) -> bool:
    """A few words out of seconds of continuous sound: an echo over noise, not speech ("Hey Falcon" is under 1.5 s)."""
    return 0 < len(text.split()) <= SPARSE_MAX_WORDS and voiced_s > SPARSE_MIN_VOICED_S


def clean_transcript(
    text: str, audio_s: float, segments: Iterable[Mapping[str, object]] = (), voiced_s: float | None = None
) -> str:
    """Full post-filter for a raw Whisper transcript."""
    text = echo_guard(text.strip(), segments)
    text = cap_words(collapse_repeats(text), word_cap(audio_s))
    if _HALLUCINATIONS.fullmatch(_fold(text)) or is_prompt_echo(text):
        return ""
    if voiced_s is not None and is_sparse(text, voiced_s):
        return ""
    return text


def sniff(data: bytes) -> str | None:
    """Container family from magic bytes: wav (RIFF/WAVE), ogg (OggS), webm (EBML header). Anything else is None.

    Text payloads such as an ffconcat playlist or an HLS/DASH manifest never match, so they are refused before a
    decoder sees them.
    """
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None
