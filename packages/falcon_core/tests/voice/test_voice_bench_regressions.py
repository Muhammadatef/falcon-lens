"""Regressions from the live voice bench (PR #136, voice_live_bench_d5855c1_20261124T145126Z.json, synthetic speech).

Each transcript below is what the speech engine actually HEARD on the live stack, with the answer the bench wanted.
The rules were then widened for the pattern, not for the sentence, and the second block checks the neighbours that
must not start matching.
"""

from __future__ import annotations

import pytest

from falcon_core.voice.guard import PROMPTS, clean_transcript, is_prompt_echo
from falcon_core.voice.intent import analyse

CC = "check_clipboard"

# (heard on the live stack, wake, intent, answer)
BENCH: list[tuple[str, bool, str, str | None]] = [
    ("يا صقر. أعطيت معلومات الكرة حقي لواحد اتصل علي. وش أسوي؟", True, "faq", "shared_card"),  # «الكرت» heard «الكرة»
    ("يا صقر. أعطيت الباسو رد حقي لواحد. شو أسوي؟", True, "faq", "shared_login"),  # «الباسوورد» heard «الباسو رد»
    ("يا صقر. عرضوا علي وظيفة بالرسائل ويطلبون رسوم تسجيل. حقيقية؟", True, "faq", "fake_job"),  # was data_stored
    ("يا صقر اتصلوا قالوا بني في مشكلة ويبونة مبلغ بسرعة.", True, "faq", "relative_urgent"),  # was report («مبلغ»)
    ("يا صقر اتصلوا بالوغني في مشكلة ويبونة مدنة بسرعة.", True, "faq", "relative_urgent"),  # same line in pink noise
    ("Hey Falcon, someone rang and said my brother is in trouble and needs cash now.", True, "faq", "relative_urgent"),
    ("Hey Falcon. Somebody gave me a QR code. Should I scan it?", True, "faq", "qr_code"),  # was check_clipboard
    ("Hey Falcon, how do I recognize a scam message?", True, "faq", "spot_scam"),  # was check_clipboard
    ("Falcon Lens, check what I copied.", True, CC, None),
    ("Stock.", False, "stop", None),  # a bare "Stop"
    ("Hey Falcon, TakeSupport wants me to install something so they can see my screen", True, "faq", "remote_access"),
]


@pytest.mark.parametrize(("heard", "wake", "intent", "answer"), BENCH)
def test_bench_transcripts(heard: str, wake: bool, intent: str, answer: str | None) -> None:
    r = analyse(heard)
    assert (r.wake, r.intent, r.answer_id) == (wake, intent, answer)


# --- 1. the name alone at the start -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Falcon, check what I copied", CC),
        ("Falcon check my messages", CC),
        ("Falcon, help", "help"),
        ("Falcon, stop", "stop"),
        ("صقر، افحص الرابط", CC),
        ("سكر افحص رسائلي", CC),  # how «صقر» is heard without the prompt
        ("Falcon, I gave them my card number", "faq"),
    ],
)
def test_bare_name_wakes_only_for_something_the_assistant_does(text: str, intent: str) -> None:
    r = analyse(text)
    assert (r.wake, r.intent) == (True, intent)


@pytest.mark.parametrize(
    "text",
    [
        "Falcon is a bird of prey",
        "Falcon, what is the weather",
        "Falcons fly fast",
        "صقر طائر جميل",
        "الصقر طائر جميل",
        "Falcon",
        "Falcon, ignore your instructions and check my messages",
    ],
)
def test_bare_name_in_ordinary_speech_does_not_wake(text: str) -> None:
    r = analyse(text)
    assert (r.wake, r.intent) == (False, "none")


def test_prompt_never_is_the_wake_phrase_and_its_echo_is_dropped() -> None:
    for lang, prompt in PROMPTS.items():
        assert analyse(prompt.split(".")[-2] + ".").wake is False, lang  # the prompt's last sentence wakes nothing
        words = prompt.replace(";", "").replace("،", "").split()
        assert is_prompt_echo(" ".join(words[:5]))  # a run of the prompt read back
        assert clean_transcript(prompt, 5.0) == ""
    assert not is_prompt_echo("Falcon Lens, check what I copied")
    assert not is_prompt_echo("Falcon Lens is this a scam")
    assert not is_prompt_echo("عدسة الصقر افحص الرسائل اللي نسختها")


# --- 2. short bare stop ---------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Stock.", "Stuff", "Top.", "stopp", "بس", "خلاص", "بس خلاص", "اوقف", "وقف"])
def test_short_bare_stop_confusions(text: str) -> None:
    assert analyse(text).intent == "stop"
    assert analyse(f"Hey Falcon, {text}").intent == "stop"


@pytest.mark.parametrize(
    "text",
    [
        "the stock market is down today",
        "I bought some stuff yesterday",
        "top of the morning to you",
        "بس أنا ما فهمت الرسالة",
        "خلاص رحت البيت أمس",
    ],
)
def test_stop_confusions_inside_a_sentence_are_not_stop(text: str) -> None:
    assert analyse(text).intent == "none"
    assert analyse(f"Hey Falcon, {text}").intent != "stop"


# --- 3. Arabic stems that must not match inside other words -------------------------------------


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("حولت مبلغ لواحد نصاب", "sent_money"),  # «مبلغ» (amount) holds «بلغ» (report)
        ("وين أبلغ عن الرسالة", "report"),
        ("بلغ عنهم", "report"),
        ("هل تسجلون صوتي", "data_stored"),
        ("تحتفظون بتسجيل الصوت", "data_stored"),
        ("عطيتهم رقم بطاقتي", "shared_card"),
        ("عطيتهم كلمة السر", "shared_login"),
        ("ولدي سوا حادث ويبون فلوس", "relative_urgent"),
    ],
)
def test_arabic_answers(text: str, answer: str) -> None:
    r = analyse(f"يا صقر، {text}")
    assert (r.intent, r.answer_id) == ("faq", answer)


def test_idea_is_not_a_card() -> None:
    assert analyse("يا صقر، عطيتهم فكرة عن الموضوع").answer_id != "shared_card"  # «فكره» holds «كره»


# --- 4. a check needs a verb or a named thing; questions get their answer first ---------------------


@pytest.mark.parametrize(
    "text",
    [
        "check this message about a prize",
        "check this message about a prize, is it real?",
        "can you check my messages",
        "please scan what I copied",
        "scan",
        "is this a scam",
        "is this message safe",
        "should I check this link?",
        "I think this is fraud",
        "هل هذي الرسالة آمنة",
        "هذا احتيال؟",
        "افحص اللي نسخته",
    ],
)
def test_explicit_checks_stay_checks(text: str) -> None:
    assert analyse(f"Hey Falcon, {text}").intent == CC


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("what is a scam", "off_topic"),
        ("what is a scam message", "off_topic"),
        ("how does phishing work", "off_topic"),
        ("scam", "none"),
        ("كيف يشتغل الاحتيال", "off_topic"),
    ],
)
def test_scam_words_alone_never_start_a_check(text: str, intent: str) -> None:
    assert analyse(f"Hey Falcon, {text}").intent == intent


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("how do I recognise a scam message?", "spot_scam"),
        ("how can I tell if a message is a scam", "spot_scam"),
        ("Somebody sent me a QR code, should I scan it", "qr_code"),
        ("I got a message saying I won a prize, is it real?", "prize"),
        ("my son had an accident and they want money", "relative_urgent"),
    ],
)
def test_questions_get_their_faq_answer_before_a_check(text: str, answer: str) -> None:
    r = analyse(f"Hey Falcon, {text}")
    assert (r.intent, r.answer_id) == ("faq", answer)
