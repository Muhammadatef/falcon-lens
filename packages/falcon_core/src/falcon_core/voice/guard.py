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


# Whisper invents stock phrases on silence or noise.
_HALLUCINATIONS = re.compile(r"(thanks? (you )?for watching\.?|you\.?|\.+|شكرا\.?)", re.IGNORECASE)


def clean_transcript(text: str, audio_s: float, segments: Iterable[Mapping[str, object]] = ()) -> str:
    """Full post-filter for a raw Whisper transcript."""
    text = echo_guard(text.strip(), segments)
    text = cap_words(collapse_repeats(text), word_cap(audio_s))
    return "" if _HALLUCINATIONS.fullmatch(text) else text


def sniff(data: bytes) -> str | None:
    """Container family from magic bytes: wav (RIFF/WAVE), ogg (OggS), webm (EBML header),
    mp4 (ISO-BMFF 'ftyp', what iOS Safari records: AAC in fragmented MP4) and aac (ADTS sync word).
    Anything else is None.

    Text payloads such as an ffconcat playlist or an HLS/DASH manifest never match, so they are refused before a
    decoder sees them.
    """
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[4:8] == b"ftyp":
        return "mp4"
    if len(data) > 7 and data[0] == 0xFF and (data[1] & 0xF6) == 0xF0:  # 12-bit sync, layer 00: ADTS (not MP3)
        return "aac"
    return None
