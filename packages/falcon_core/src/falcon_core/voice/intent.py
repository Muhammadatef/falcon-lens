"""Wake phrase and intent detection for the "Hey Falcon" voice assistant. Deterministic, no LLM.

The wake-phrase structure (normalise, match only when the phrase opens the utterance after one
optional filler, return the rest) is adapted from the owner's Neo project; the phrases, the fuzzy
matching and the intents are Falcon's. Transcripts are never logged here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from falcon_core.voice.faq import is_injection, match_rules
from falcon_core.voice.textnorm import _TOKEN, MAX_CHARS, edit_distance, norm_word, normalise

Intent = Literal["check_clipboard", "check_text", "help", "stop", "faq", "off_topic", "none"]

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


def _bare_name_rest(text: str) -> str:
    """The text after a bare leading name ("Falcon, ..." / «صقر، ...»), or "" when it does not open with one."""
    spans = [(m.end(), norm_word(m.group())) for m in _TOKEN.finditer(text)]
    spans = [s for s in spans if s[1]]
    if len(spans) < 2 or not (_is_falcon(spans[0][1]) or spans[0][1] in ("صقر", "سقر", "سكر")):
        return ""
    return text[spans[0][0] :].lstrip(" \t\n\r,.،؛;:!?؟-–—…\"'«»").strip()[:MAX_CHARS]


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
# What speech recognition writes for a short, bare "Stop" / «توقف» (the live bench heard "Stock."). Read as stop
# ONLY when they are the whole utterance (one or two words): inside a sentence they keep their own meaning.
_STOP_SHORT = frozenset(
    {"stock", "stuff", "top", "stopp", "stops", "stopped", "stahp", "shtop", "stob"}
    | {"بس", "خلاص", "اوقف", "توقفوا", "وقفي", "وقفوا", "توقفي", "اسكت", "توكف", "تواقف"}
)
_STOP_SHORT_MAX = 2
_HELP_TOKENS = frozenset({"help", "instructions", "guide", "tutorial"})
_HELP_PHRASES = (
    "what can you do", "what do you do", "how do you work", "how to use", "how do i use", "who are you",
    "ساعد", "مساعده", "تعليمات", "كيف استخدم", "ماذا تفعل", "شو تسوي", "ايش تسوي", "كيف تعمل",
)  # fmt: skip
_CLIPBOARD_EN = ("clipboard", "copied", "copy", "paste")
_CLIPBOARD_AR = ("نسخت", "الحافظه", "حافظه", "نسخ")
_TEXT_TOKENS = frozenset({"text", "sms", "نص", "النص", "نصي", "نصيه"})
_VERBS_EN = ("check", "scan", "verif", "analy", "examin", "investigat")
_QUESTION_WORDS = frozenset(
    {"should", "does", "do", "is", "are", "how", "what", "where", "who", "why", "when", "which", "can", "could"}
    | {"هل", "كيف", "شو", "وش", "ليش", "وين", "شلون", "منو", "ايش", "شنو", "لماذا", "ماذا", "متى", "اين", "مين"}
)
_VERBS_AR = ("افحص", "فحص", "تحقق", "تاكد", "حلل")
# Words that only DESCRIBE a scam. Alone they never start a check ("how do I recognise a scam message?" is a
# question, not a command): they count only next to "this"/«هذا» or a named thing (message, link, clipboard).
_SCAM_EN = ("scam", "phish", "fraud", "suspic")
_SCAM_AR = ("احتيال", "نصب", "نصاب")
_POINTERS = frozenset(
    {"this", "that", "these", "those", "it", "them", "my"}
    | {"هذا", "هذي", "هذه", "هاذي", "هاذا", "هاي", "هذول", "هذيل", "ذي", "ها"}
)
# A question inside the sentence ("Somebody gave me a QR code. Should I scan it?"): its FAQ answer comes first.
_ASKING = (
    "should i", "shall i", "how do i", "how can i", "how to", "how would i", "can i", "could i", "do i", "is it",
    "what do i", "what should", "what if", "هل", "كيف", "شلون", "شو اسوي", "وش اسوي", "ايش اسوي", "شنو اسوي",
)  # fmt: skip
_POLITE = frozenset({"please", "pls", "kindly", "can", "could", "you", "لو", "سمحت", "تكفي", "تكرم", "فضلا", "ممكن"})
# Names accepted WITHOUT a greeting ("Falcon, check my messages" / «صقر، افحص الرابط»), and only when what follows is
# something the assistant does: a sentence that merely starts with the word ("Falcon is a bird") never wakes it.
_BARE_NAME_INTENTS = frozenset({"check_clipboard", "check_text", "help", "stop", "faq"})


def _prefix(toks: list[str], stems: tuple[str, ...]) -> bool:
    return any(t.startswith(s) for t in toks for s in stems)


def _contains(toks: list[str], stems: tuple[str, ...]) -> bool:
    return any(s in t for t in toks for s in stems)


def _classify(command: str) -> tuple[Intent, str | None, bool]:
    """(intent, FAQ name when intent is `faq`, True when the text tried to override the assistant's instructions)."""
    norm = normalise(command)
    toks = norm.split()
    if not toks:
        return "none", None, False
    padded = f" {norm} "
    if any(t in _STOP for t in toks) or any(f" {p} " in padded for p in _STOP_PHRASES):
        return "stop", None, False
    if len(toks) <= _STOP_SHORT_MAX and all(t in _STOP_SHORT for t in toks):
        return "stop", None, False
    if is_injection(command):
        return "off_topic", None, True
    run_lens = "run" in toks and ("lens" in toks or any(_is_falcon(t) for t in toks))
    plain = [t for t in toks if not t.startswith("verification")]
    verb = _prefix(plain, _VERBS_EN) or _contains(toks, _VERBS_AR)
    lead = [t for t in toks if t not in _POLITE][:1]
    lead_verb = bool(lead) and (_prefix(lead, _VERBS_EN) or _contains(lead, _VERBS_AR))
    asking = not lead_verb and (
        toks[0] in _QUESTION_WORDS or "?" in command or "؟" in command or any(f" {q} " in padded for q in _ASKING)
    )
    pointed = any(t in _POINTERS for t in toks) or any(t.startswith("هال") for t in toks)
    named = _contains(toks, tuple(s for s in _CLIP_AR if s not in _SCAM_AR)) or _prefix(
        plain, tuple(s for s in _CLIP_EN if s not in _SCAM_EN)
    )
    scam_word = _contains(toks, _SCAM_AR) or _prefix(toks, _SCAM_EN)
    faq = match_rules(command)
    # An imperative check ("check this message about a prize") stays a check; a question or a story gets its FAQ answer.
    if faq and not (verb and named and not asking):
        return "faq", faq, False
    # A check needs a named thing or a verb; a scam word counts only when it points at something ("is THIS a scam").
    # A question that points at nothing ("what is a scam message") is not a command.
    clipish = run_lens or ((named or (scam_word and pointed)) and (pointed or not asking))
    if clipish:
        has_clip = _prefix(toks, _CLIPBOARD_EN) or _contains(toks, _CLIPBOARD_AR)
        named_text = any(t in _TEXT_TOKENS for t in toks) and not any(t.startswith("messag") for t in toks)
        # "check this text" / «افحص هذا النص» names the content; everything else reads the clipboard.
        return ("check_text" if named_text and verb and not has_clip else "check_clipboard"), None, False
    if any(t in _HELP_TOKENS for t in toks) or any(p in padded for p in _HELP_PHRASES):
        return "help", None, False
    # Something was said after the wake phrase that is not ours: a fixed polite redirect (one word is just noise).
    return ("off_topic" if len(toks) >= 2 else "none"), None, False


@dataclass(frozen=True)
class VoiceResult:
    wake: bool
    intent: Intent
    command: str
    #: Name of the pre-written FAQ answer (`faq.<name>` clip) when intent is `faq`.
    answer_id: str | None = None
    #: True when the command tried to override the assistant's instructions (always answered with a redirect).
    injection: bool = False


def analyse(transcript: str, *, follow_up: bool = False) -> VoiceResult:
    """Wake + intent for one transcript.

    Intent is read from the command after the wake phrase. Without the wake phrase only a short,
    bare stop word («توقف», "stop") counts, so the user can interrupt without saying the name.
    `follow_up` marks the utterance right after a bare wake phrase: it is a command even without the wake phrase.
    """
    woke, rest = match_wake(transcript)
    if woke:
        intent, answer, inj = _classify(rest)
        return VoiceResult(True, intent, rest, answer, inj)
    bare = _bare_name_rest(transcript)
    if bare and not follow_up:
        intent, answer, inj = _classify(bare)
        if intent in _BARE_NAME_INTENTS and not inj:
            return VoiceResult(True, intent, bare, answer, inj)
    if follow_up:
        command = transcript.strip()[:MAX_CHARS]
        intent, answer, inj = _classify(command)
        return VoiceResult(True, intent, command, answer, inj)
    toks = normalise(transcript).split()
    if 0 < len(toks) <= 3 and _classify(transcript)[0] == "stop":
        return VoiceResult(False, "stop", transcript.strip()[:MAX_CHARS])
    return VoiceResult(False, "none", "")
