"""Wake phrase and intent detection for the "Hey Falcon" voice assistant. Deterministic, no LLM.

The wake-phrase structure (normalise, match only when the phrase opens the utterance after one
optional filler, return the rest) is adapted from the owner's Neo project; the phrases, the fuzzy
matching and the intents are Falcon's. Transcripts are never logged here.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

Intent = Literal["check_clipboard", "check_text", "help", "stop", "none"]
MAX_CHARS = 300

_MARKS = re.compile("[ً-ٰٟـ]")  # diacritics + tatweel
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ئ": "ي", "ؤ": "و"})
_TOKEN = re.compile("[\\wً-ٰٟـ']+")


def norm_word(word: str) -> str:
    """Lowercase, NFKC, no diacritics/tatweel, alef/yeh/teh-marbuta folded, no punctuation."""
    w = unicodedata.normalize("NFKC", word).lower()
    w = _MARKS.sub("", w).translate(_FOLD)
    return "".join(ch for ch in w if ch.isalnum())


def normalise(text: str) -> str:
    """Normalised text with single spaces (punctuation becomes a space)."""
    return " ".join(t for t in (norm_word(m.group()) for m in _TOKEN.finditer(text)) if t)


def edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


# --- wake phrase -----------------------------------------------------------------------------

_FALCON_EN = "falcon"
_GREET_EN = frozenset(
    {"hey", "hay", "hei", "heya", "hi", "hai", "hye", "ok", "okay", "okey", "okie", "ya", "yaa", "hala", "hello"}
)
_GREET_AR = frozenset({"يا", "هاي", "هلا", "هلو", "اهلا", "هي", "اوكي", "ويا"})
_GREETINGS = _GREET_EN | _GREET_AR
_FILLERS = frozenset({"so", "um", "uh", "well", "طيب", "يلا", "امم"})
_SAQR = frozenset({"صقر", "الصقر", "سقر", "السقر", "صقور", "سكر"})  # «سكر»: Whisper hears «صقر» as «سكر»
_LENS_EN = frozenset({"lens", "lenz", "lins", "lense", "lenses", "lands", "lance"})
_MAX_START = 2


def _is_falcon(tok: str) -> bool:
    """English wake token (Latin script). Whisper writes it many ways: allow edit distance <= 2."""
    if len(tok) < 4:
        return False
    if not tok.isascii():
        return False  # Arabic wakes only on «صقر» (see _SAQR); «فالكون» is not a wake word
    return tok[0] in "fvp" and any(c in tok for c in "ckq") and len(tok) <= 9 and edit_distance(tok, _FALCON_EN) <= 2


def _is_name(tok: str) -> bool:
    return _is_falcon(tok) or tok in _SAQR


def _glued(tok: str) -> bool:
    """«ياصقر», «هلاصقر», «heyfalcon»: greeting and name written as one word."""
    for g in sorted(_GREETINGS, key=len, reverse=True):
        if tok.startswith(g) and len(tok) > len(g) and _is_name(tok[len(g) :]):
            return True
    return False


def _is_adasa(tok: str) -> bool:
    return len(tok) >= 3 and edit_distance(tok, "عدسه") <= 1


def _is_saqr_def(tok: str) -> bool:
    return len(tok) >= 4 and edit_distance(tok, "الصقر") <= 1


def _match_at(t: list[str], i: int) -> int:
    """Number of tokens consumed by a wake phrase starting at t[i], or 0."""
    a = t[i]
    b = t[i + 1] if i + 1 < len(t) else ""
    c = t[i + 2] if i + 2 < len(t) else ""
    if _glued(a):
        return 1
    if a in _GREETINGS and _is_name(b):
        return 2
    if a in _GREETINGS and _is_adasa(b) and _is_saqr_def(c):
        return 3
    if a in _GREETINGS and len(b) > 6 and b.startswith("عدس") and _is_saqr_def(b[4:]):
        return 2  # «يا عدسةالصقر» (Whisper joins the words)
    if _is_falcon(a) and b in _LENS_EN:
        return 2
    if _is_adasa(a) and _is_saqr_def(b):
        return 2
    if len(a) > 6 and a.startswith("عدس") and _is_saqr_def(a[4:]):
        return 1
    return 0


def match_wake(text: str) -> tuple[bool, str]:
    """(woke, rest of the utterance after the wake phrase, in the speaker's own spelling).

    Wakes only when the phrase opens the utterance, after at most two filler words.
    """
    spans = [(m.start(), m.end(), norm_word(m.group())) for m in _TOKEN.finditer(text)]
    spans = [s for s in spans if s[2]]
    toks = [s[2] for s in spans]
    for i in range(min(_MAX_START, len(toks) - 1) + 1):
        if i and toks[i - 1] not in _FILLERS:
            break
        n = _match_at(toks, i)
        if n:
            end = spans[i + n - 1][1]
            rest = text[end:].lstrip(" \t\n\r,.،؛;:!?؟-–—…\"'«»")
            return True, rest.strip()[:MAX_CHARS]
    return False, ""


# --- intent ----------------------------------------------------------------------------------

_CLIP_EN = (
    "messag", "link", "email", "mail", "clipboard", "copied", "copy", "paste", "scam", "phish", "fraud",
    "suspic", "check", "verif", "scan", "sms", "text", "investigat", "analy", "examin", "url", "website",
)  # fmt: skip
_CLIP_AR = (
    "رساله", "رسايل", "رسال", "رابط", "روابط", "ايميل", "بريد", "نسخت", "نسخ", "الحافظه", "حافظه",
    "احتيال", "نصب", "نصاب", "افحص", "فحص", "تحقق", "تاكد", "شغل", "حلل",
)  # fmt: skip
_STOP = frozenset(
    {"stop", "cancel", "nevermind", "quit", "exit"} | {"توقف", "وقف", "قف", "الغاء", "الغي", "الغ", "كفايه", "توقفي"}
)
_STOP_PHRASES = ("never mind", "that s all", "thats all")
_HELP_TOKENS = frozenset({"help", "instructions", "guide", "tutorial"})
_HELP_PHRASES = (
    "what can you do", "what do you do", "how do you work", "how to use", "how do i use", "who are you",
    "ساعد", "مساعده", "تعليمات", "كيف استخدم", "ماذا تفعل", "شو تسوي", "ايش تسوي", "كيف تعمل",
)  # fmt: skip
_CLIPBOARD_EN = ("clipboard", "copied", "copy", "paste")
_CLIPBOARD_AR = ("نسخت", "الحافظه", "حافظه", "نسخ")
_TEXT_TOKENS = frozenset({"text", "sms", "نص", "النص", "نصي", "نصيه"})
_VERBS_EN = ("check", "scan", "verif", "analy", "examin", "investigat")
_VERBS_AR = ("افحص", "فحص", "تحقق", "تاكد", "حلل")


def _prefix(toks: list[str], stems: tuple[str, ...]) -> bool:
    return any(t.startswith(s) for t in toks for s in stems)


def _contains(toks: list[str], stems: tuple[str, ...]) -> bool:
    return any(s in t for t in toks for s in stems)


def _classify(command: str) -> Intent:
    norm = normalise(command)
    toks = norm.split()
    if not toks:
        return "none"
    padded = f" {norm} "
    if any(t in _STOP for t in toks) or any(f" {p} " in padded for p in _STOP_PHRASES):
        return "stop"
    run_lens = "run" in toks and ("lens" in toks or any(_is_falcon(t) for t in toks))
    if run_lens or _contains(toks, _CLIP_AR) or _prefix(toks, _CLIP_EN):
        has_clip = _prefix(toks, _CLIPBOARD_EN) or _contains(toks, _CLIPBOARD_AR)
        verb = _prefix(toks, _VERBS_EN) or _contains(toks, _VERBS_AR)
        named_text = any(t in _TEXT_TOKENS for t in toks) and not any(t.startswith("messag") for t in toks)
        # "check this text" / «افحص هذا النص» names the content; everything else reads the clipboard.
        return "check_text" if named_text and verb and not has_clip else "check_clipboard"
    if any(t in _HELP_TOKENS for t in toks) or any(p in padded for p in _HELP_PHRASES):
        return "help"
    return "none"


@dataclass(frozen=True)
class VoiceResult:
    wake: bool
    intent: Intent
    command: str


def analyse(transcript: str) -> VoiceResult:
    """Wake + intent for one transcript.

    Intent is read from the command after the wake phrase. Without the wake phrase only a short,
    bare stop word («توقف», "stop") counts, so the user can interrupt without saying the name.
    """
    woke, rest = match_wake(transcript)
    if woke:
        return VoiceResult(True, _classify(rest), rest)
    toks = normalise(transcript).split()
    if 0 < len(toks) <= 3 and _classify(transcript) == "stop":
        return VoiceResult(False, "stop", transcript.strip()[:MAX_CHARS])
    return VoiceResult(False, "none", "")
