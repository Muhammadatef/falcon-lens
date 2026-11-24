from __future__ import annotations

import pytest

from falcon_core.voice.guard import clean_transcript, collapse_repeats, echo_guard, word_cap
from falcon_core.voice.intent import analyse, match_wake, normalise

CC = "check_clipboard"
CT = "check_text"

# (transcript, wake, intent)
EN_CASES: list[tuple[str, bool, str]] = [
    ("Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens", True, CC),
    ("Hey Falcon", True, "none"),
    ("Hey Falcon.", True, "none"),
    ("Hi Falcon, check my clipboard", True, CC),
    ("OK Falcon, I copied a link", True, CC),
    ("Okay Falcon check this link", True, CC),
    ("Falcon Lens, scan this message", True, CC),
    ("Falcon lens", True, "none"),
    ("hey falcon i got a suspicious email", True, CC),
    ("hey falcon is this a scam", True, CC),
    ("hey falcon verify the sms i copied", True, CC),
    ("hey falcon run falcon lens", True, CC),
    ("hey falcon please run lens", True, CC),
    ("hey falcon what can you do", True, "help"),
    ("hey falcon help", True, "help"),
    ("hey falcon how do you work", True, "help"),
    ("hi falcon how to use this", True, "help"),
    ("hey falcon stop", True, "stop"),
    ("hey falcon cancel", True, "stop"),
    ("hey falcon never mind", True, "stop"),
    ("hey falcon what is the weather", True, "off_topic"),
    ("hey falcon tell me a joke", True, "off_topic"),
    ("hey falcon check this text", True, CT),
    ("Hey Falken, check my messages", True, CC),
    ("Hey Falkon check the link", True, CC),
    ("hey folcon i received a scam message", True, CC),
    ("hay falcon check the email", True, CC),
    ("heyfalcon check my clipboard", True, CC),
    ("Hi, Falcon. I copied a message", True, CC),
    ("hey valcon check this message", True, CC),
    ("hey falcom check the link", True, CC),
    ("so hey falcon check the link", True, CC),
    ("um okay falcon check my messages", True, CC),
    ("hey falcon, someone sent me a phishing link", True, CC),
    ("hey falcon, I think this is fraud", True, CC),
    ("hey falcon can you analyse this website", True, CC),
    ("The falcon is a bird of prey", False, "none"),
    ("hey there, check this link", False, "none"),
    ("hello how are you", False, "none"),
    ("I saw a falcon yesterday", False, "none"),
    ("hey salon check the link", False, "none"),
    ("hey fallen angels check this", False, "none"),
    ("lens cleaning fluid", False, "none"),
    ("check this message", False, "none"),
    ("what a nice day", False, "none"),
    ("stop", False, "stop"),
    ("Stop!", False, "stop"),
    ("cancel", False, "stop"),
    ("please stop that", False, "stop"),
    ("", False, "none"),
    ("   ", False, "none"),
    ("you can stop whenever you want to be honest with me now", False, "none"),
    ("Hey Falcon! Check my clipboard please.", True, CC),
    ("Falcon lands, scan this message", True, CC),
]

AR_CASES: list[tuple[str, bool, str]] = [
    ("يا صقر، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر", True, CC),
    ("يا صقر", True, "none"),
    ("هاي صقر افحص الرابط", True, CC),
    ("هلا صقر نسخت رسالة", True, CC),
    ("يا صقر وصلتني رسالة مشبوهة", True, CC),
    ("هلا صقر تحقق من الإيميل", True, CC),
    ("عدسة الصقر افحص هذه الرسالة", True, CC),
    ("عدسة الصقر", True, "none"),
    ("يا عدسة الصقر شغل", True, CC),
    ("يا عدسة الصقر، وصلني رابط غريب", True, CC),
    ("ياصقر افحص الرابط", True, CC),
    ("هلاصقر وصلتني رسايل", True, CC),
    ("يا صقر شوف الرسالة", True, CC),
    ("يا صقر وصلني بريد مشبوه", True, CC),
    ("هاي صقر افحص", True, CC),
    ("يا صقر تحقق من الرابط", True, CC),
    ("ياصقر افحص الرسالة", True, CC),
    ("هلاصقر وصلتني رسالة", True, CC),
    ("يا صقر ساعدني", True, "help"),
    ("يا صقر مساعدة", True, "help"),
    ("هلا صقر ماذا تفعل", True, "help"),
    ("يا صقر كيف استخدم الخدمة", True, "help"),
    ("يا صقر توقف", True, "stop"),
    ("يا صقر إلغاء", True, "stop"),
    ("هلا صقر كفاية", True, "stop"),
    ("يا صقر كيف حال الطقس", True, "off_topic"),
    ("يا صقر احكي لي نكتة", True, "off_topic"),
    ("يا صقر هذا احتيال؟", True, CC),
    ("يا صقر وصلتني رسالة نصب", True, CC),
    ("هاي صقر نسخت الرابط", True, CC),
    ("يا صقر الحافظة فيها رابط", True, CC),
    ("يا صقر افحص هذا النص", True, CT),
    ("طيب يا صقر افحص الرسالة", True, CC),
    ("يا صقر، شغّل", True, CC),
    ("اهلا صقر وصلني ايميل", True, CC),
    ("يا عدسه الصقر افحص", True, CC),
    ("عدسةالصقر افحص الرابط", True, CC),
    ("يا صقر ساعدني", True, "help"),
    ("الصقر طائر جميل", False, "none"),
    ("أهلا بك كيف حالك", False, "none"),
    ("وصلتني رسالة غريبة", False, "none"),
    ("افحص الرابط", False, "none"),
    ("يا محمد افحص الرابط", False, "none"),
    ("رأيت صقرا في الصحراء", False, "none"),
    ("توقف", False, "stop"),
    ("إلغاء", False, "stop"),
    ("وقف", False, "stop"),
    ("", False, "none"),
    ("يا صقر افحص الرسائل", True, CC),
    ("يا سكر توقف", True, "stop"),
    ("يا الصقر افحص الرابط", True, CC),
    ("يا فالكون افحص الرابط", False, "none"),
    ("هلا فالكون وصلتني رسالة", False, "none"),
    ("يافالكون افحص الرسالة", False, "none"),
]


@pytest.mark.parametrize(("text", "wake", "intent"), EN_CASES)
def test_english(text: str, wake: bool, intent: str) -> None:
    r = analyse(text)
    assert (r.wake, r.intent) == (wake, intent), text


@pytest.mark.parametrize(("text", "wake", "intent"), AR_CASES)
def test_arabic(text: str, wake: bool, intent: str) -> None:
    r = analyse(text)
    assert (r.wake, r.intent) == (wake, intent), text


def test_case_counts() -> None:
    assert len(EN_CASES) >= 40
    assert len(AR_CASES) >= 40


def test_owner_demo_lines_command() -> None:
    en = analyse("Hey Falcon, I have received multiple messages that I feel it's scam, run Falcon Lens")
    assert en.command.startswith("I have received multiple messages")
    ar = analyse("يا صقر، وصلتني رسائل كثيرة أشك أنها احتيال، شغّل عدسة الصقر")
    assert ar.command.startswith("وصلتني رسائل")


def test_command_capped_and_empty_without_wake() -> None:
    r = analyse("hey falcon " + "check this link " * 100)
    assert len(r.command) <= 300
    assert analyse("check this link").command == ""


def test_normalise() -> None:
    assert normalise("يَا صَقْرْ!") == "يا صقر"
    assert normalise("عدسة الصقر") == "عدسه الصقر"
    assert normalise("أإآ ـــ ى") == "ااا ي"
    assert normalise("Hey, FALCON...") == "hey falcon"


def test_match_wake_rest() -> None:
    assert match_wake("Hey Falcon, check this") == (True, "check this")
    assert match_wake("nothing here") == (False, "")


def test_guard() -> None:
    assert collapse_repeats("a b a b a b a b a b c") == "a b a b c"
    assert collapse_repeats("room 5 room 5 room 5 room 5") == "room 5 room 5 room 5 room 5"
    assert echo_guard("x", [{"compression_ratio": 3.0}]) == ""
    assert echo_guard("x", [{"compression_ratio": 1.0}]) == "x"
    assert word_cap(5) == 23
    assert clean_transcript("Thank you for watching", 3) == ""
    assert clean_transcript("hello there", 3) == "hello there"
