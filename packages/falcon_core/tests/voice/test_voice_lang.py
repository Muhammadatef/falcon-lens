"""The reply language follows the speaker's own script, never the detector's guess."""

from __future__ import annotations

import pytest

from falcon_core.voice.intent import analyse, script_lang, wake_lang


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Hey Falcon", "en"),
        ("Hey Falcon, check my messages", "en"),
        ("OK Falcon what can you do", "en"),
        ("Falcon Lens, scan this", "en"),
        ("يا صقر", "ar"),
        ("ياصقر افحص رسائلي", "ar"),
        ("يا سكر", "ar"),
        ("هلا صقر", "ar"),
        ("عدسة الصقر افحص هذه الرسالة", "ar"),
        ("يا صقر، does the bank ask for my code", "en"),  # command clearly Latin
        ("Hey Falcon, هل البنك يطلب مني الرمز", "ar"),  # command clearly Arabic
        ("Hey Falcon, شيّك اللي نسخته", "ar"),
    ],
)
def test_wake_utterance_language_is_the_script(text: str, lang: str) -> None:
    r = analyse(text)
    assert r.wake and r.lang == lang, text


def test_mixed_command_keeps_the_wake_language() -> None:
    assert wake_lang("Hey Falcon", "check the رابط link") == "en"
    assert wake_lang("يا صقر", "افحص this رابط") == "ar"


def test_follow_up_language_is_its_own_script() -> None:
    assert analyse("شيّك اللي نسخته", follow_up=True).lang == "ar"
    assert analyse("check what I copied", follow_up=True).lang == "en"


def test_bare_stop_and_noise_use_their_script() -> None:
    assert analyse("stop").lang == "en"
    assert analyse("توقف").lang == "ar"
    assert analyse("what is for dinner").lang == "en"


def test_no_letters_means_no_opinion() -> None:
    assert script_lang("123 ...") is None
    assert analyse("", follow_up=True).lang is None
