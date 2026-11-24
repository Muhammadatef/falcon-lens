"""Scam-safety FAQ matching for the voice assistant. Deterministic keyword rules and a prompt-injection screen.

No text is generated here or anywhere in the voice path: a match returns the NAME of a pre-written, pre-recorded
answer (`faq.<name>` in i18n/voice_faq.yaml). Rules are written as groups of stems: a rule fires when, for at least
one alternative, every group has a hit (a group is an OR of stems). Arabic stems are matched anywhere inside a token
(prefixes such as و/ب/ال stick to words), English stems at the start of a token. Phrases (with spaces) match inside
the normalised text. All stems are normalised with the same folding as the transcript.
"""

from __future__ import annotations

from falcon_core.voice.textnorm import norm_word, normalise

Group = tuple[str, ...]
Alt = tuple[Group, ...]


def _n(stem: str) -> str:
    return " ".join(norm_word(w) for w in stem.split())


def _g(*stems: str) -> Group:
    return tuple(_n(s) for s in stems)


# Short English stems that would otherwise match inside other words (dir/direct, pin/pink, cid/cider).
_WHOLE_WORD = frozenset({"dir", "pin", "cid", "qr", "otp", "cvv", "tap", "job"})


def _hit(norm: str, toks: list[str], group: Group) -> bool:
    padded = f" {norm} "
    for s in group:
        if " " in s:
            if s in norm:
                return True
        elif s.isascii():
            if s in _WHOLE_WORD:
                if s in toks:
                    return True
            elif any(t.startswith(s) for t in toks):
                return True
        elif any(s in t for t in toks):
            return True
        if f" {s} " in padded:
            return True
    return False


# Past-tense "I did X" cues.
_DID_SHARE = _g(
    "shared", "gave", "sent", "told", "entered", "typed", "disclosed", "provided", "revealed",
    "شاركت", "اعطيت", "ارسلت", "قلت", "ادخلت", "دخلت", "كتبت", "اعطيتهم", "عطيت", "بعثت", "سلمت",
)  # fmt: skip
_CARD = _g(
    "card", "cvv", "otp", "one time", "pin", "bank detail", "account number", "iban",
    "بطاق", "كرت", "كارد", "رمز", "كود", "حسابي", "رقم الحساب", "ايبان", "سي في في", "بيانات البنك",
)  # fmt: skip
_LOGIN = _g(
    "password", "passcode", "login", "log in", "username", "credentials", "كلمه السر", "كلمه المرور", "الرقم السري",
    "باسورد", "يوزر", "بيانات الدخول", "رقمي السري", "سر الحساب",
)  # fmt: skip
_LINK = _g("link", "url", "رابط", "لينك", "الرابط", "روابط")
_CLICKED = _g(
    "clicked", "tapped", "pressed", "opened", "click", "tap", "ضغطت", "دسته", "فتحت", "كبست", "دست", "ضغطه", "ضغط",
    "فتحته", "فتحتها", "كليك",
)  # fmt: skip
_MONEY = _g("money", "payment", "funds", "cash", "فلوس", "مبلغ", "اموال", "دراهم", "تحويل", "الفلوس")
_PAID = _g(
    "transferred", "paid", "wired", "deposited", "sent money", "transfer", "حولت", "دفعت", "حولتها", "سددت", "ودعت",
    "حولتله", "حولتلهم",
)  # fmt: skip
_CALL = _g(
    "call", "calls", "called", "calling", "phone", "rang", "contacted", "اتصل", "يتصل", "كلمني", "مكالم", "اتصال",
    "تلفون", "رن", "يكلمني", "كلمت",
)  # fmt: skip

RULES: dict[str, tuple[Alt, ...]] = {
    "qr_code": ((_g("qr", "كيو ار", "كيوار", "كيو اي", "باركود", "barcode", "رمز استجابه"),),),
    "agents": (
        (_g("baseer", "basir", "baseir", "bassir", "basser", "بصير", "بسير", "بصر", "درع", "dir", "deer"),),
        ((_g("two agents", "both agents", "agents", "الوكيلين", "وكلاء", "الوكيل")),),
    ),
    "about": (
        (
            _g(
                "falcon lens",
                "عدسه الصقر",
                "عدسه صقر",
                "this app",
                "this assistant",
                "your app",
                "who made you",
                "who built",
                "about you",
                "about yourself",
                "عن نفسك",
                "من انت",
                "منو انت",
                "مين انت",
                "شو انت",
                "وش انت",
                "شنو انت",
                "من صنعك",
                "من سواك",
                "هذا التطبيق",
            ),
            _g(
                "what",
                "who",
                "tell",
                "explain",
                "about",
                "ايش",
                "وش",
                "شو",
                "شنو",
                "ما هي",
                "ما هو",
                "من",
                "عرف",
                "اشرح",
                "عن",
                "قول",
                "تعريف",
            ),
        ),
        (_g("what are you", "what is this", "who are you", "ايش هذا", "شو هذا", "وش هذا", "ما هذا", "ما هذي"),),
    ),
    "data_stored": (
        (
            _g(
                "store",
                "stored",
                "save",
                "saved",
                "keep",
                "kept",
                "record",
                "recorded",
                "recording",
                "delete",
                "deleted",
                "logged",
                "تخزن",
                "تحفظ",
                "محفوظ",
                "تسجل",
                "تحذف",
                "حفظ",
                "يخزن",
                "يسجل",
                "يحفظ",
                "تسجيل",
                "يحذف",
                "مخزن",
                "تخزين",
                "يتخزن",
                "ينسجل",
                "تنسجل",
                "ينحفظ",
                "تنحفظ",
                "ينحذف",
                "تنحذف",
            ),
            _g(
                "data",
                "audio",
                "voice",
                "message",
                "messages",
                "recording",
                "my text",
                "بيان",
                "صوت",
                "رسالت",
                "رسايل",
                "كلام",
                "مسج",
            ),
        ),
        (_g("privacy", "خصوصي", "خصوصيت"),),
    ),
    "limits": (
        (
            _g(
                "always right",
                "always correct",
                "accurate",
                "accuracy",
                "guarantee",
                "reliable",
                "can you be wrong",
                "make mistakes",
                "how sure",
                "how accurate",
                "تغلط",
                "دقيق",
                "دقه",
                "تضمن",
                "اخطاء",
                "غلطان",
                "متاكد",
                "صح دايم",
                "صح دائم",
            ),
            _g("you", "your", "falcon", "انت", "انتي", "عليك", "نتيجتك", "تقييمك", "عدسه", "verdict"),
        ),
    ),
    "fake_police": (
        (
            _g(
                "police",
                "prosecution",
                "interior ministry",
                "cid",
                "الشرطه",
                "شرطه",
                "نيابه",
                "الداخليه",
                "مباحث",
                "ضابط",
                "officer",
            ),
            _CALL + _MONEY + _g("fine", "arrest", "pay", "warrant", "غرامه", "قضيه", "مطلوب", "يطلب", "قبض"),
        ),
    ),
    "sent_money": ((_PAID, _g("scam", "scammer", "fraud", "fake", "نصاب", "نصب", "احتيال", "مزيف", "وهمي") + _MONEY),),
    "shared_card": ((_DID_SHARE, _CARD),),
    "shared_login": ((_DID_SHARE, _LOGIN),),
    "clicked_link": ((_CLICKED, _LINK),),
    "remote_access": (
        (
            _g(
                "anydesk",
                "teamviewer",
                "remote",
                "screen share",
                "share my screen",
                "share screen",
                "install",
                "download app",
                "control my phone",
                "control my computer",
                "تحميل برنامج",
                "نزل برنامج",
                "نزل تطبيق",
                "تحميل تطبيق",
                "شاشتي",
                "شاشه",
                "تحكم",
                "ايني ديسك",
                "تيم فيور",
                "عن بعد",
                "نزلت برنامج",
            ),
            _CALL
            + _g(
                "support",
                "someone",
                "asks",
                "asking",
                "told",
                "agent",
                "اتصل",
                "دعم",
                "موظف",
                "واحد",
                "احد",
                "يقول",
                "يطلب",
                "طلب",
            ),
        ),
    ),
    "relative_urgent": (
        (
            _g(
                "relative",
                "my son",
                "my daughter",
                "my father",
                "my mother",
                "grandson",
                "family member",
                "قريب",
                "ابني",
                "بنتي",
                "ولدي",
                "ابوي",
                "امي",
                "حفيد",
                "عيالي",
                "اهلي",
                "احد من اهلي",
                "اخوي",
                "اختي",
            ),
            _g(
                "accident",
                "arrest",
                "hospital",
                "stuck",
                "abroad",
                "trouble",
                "urgent",
                "emergency",
                "حادث",
                "محتجز",
                "مستشفى",
                "مسجون",
                "طوارئ",
                "عاجل",
                "مشكله",
                "موقوف",
                "محتاج فلوس",
                "يحتاج فلوس",
                "need money",
                "needs money",
            ),
        ),
    ),
    "friend_money": (
        (
            _g(
                "friend",
                "brother",
                "sister",
                "cousin",
                "colleague",
                "whatsapp",
                "صديقي",
                "ربعي",
                "صاحبي",
                "واتساب",
                "واتس",
                "زميلي",
                "حساب صديق",
            ),
            _g(
                "money",
                "loan",
                "transfer",
                "borrow",
                "فلوس",
                "سلفه",
                "حول",
                "مبلغ",
                "يطلب",
                "استلف",
                "يسلف",
                "يطلبون",
            ),
        ),
    ),
    "bank_link": (
        (
            _g("bank", "بنك"),
            _LINK,
            _g(
                "update",
                "details",
                "account",
                "verify",
                "suspend",
                "frozen",
                "تحديث",
                "حدث",
                "بيانات",
                "حسابي",
                "موقوف",
                "تجميد",
                "تحقق",
                "ايقاف",
            ),
        ),
    ),
    "parcel_fee": (
        (
            _g(
                "parcel",
                "package",
                "delivery",
                "courier",
                "shipment",
                "shipping",
                "طرد",
                "شحن",
                "توصيل",
                "بريد",
                "التوصيل",
            ),
            _g(
                "fee",
                "pay",
                "payment",
                "customs",
                "charge",
                "sms",
                "message",
                "text",
                "رسوم",
                "دفع",
                "جمارك",
                "رساله",
                "مسج",
                "رسايل",
            ),
        ),
    ),
    "prize": (
        (
            _g(
                "prize",
                "lottery",
                "raffle",
                "winner",
                "giveaway",
                "i won",
                "you won",
                "have won",
                "جايزه",
                "جائزه",
                "سحب",
                "ربحت",
                "فزت",
                "يانصيب",
                "لوتري",
                "مسابقه",
                "فايز",
                "كسبت",
            ),
        ),
    ),
    "investment": (
        (
            _g(
                "invest",
                "crypto",
                "bitcoin",
                "forex",
                "trading",
                "guaranteed profit",
                "high returns",
                "استثمار",
                "استثمر",
                "عملات رقميه",
                "كريبتو",
                "بيتكوين",
                "ارباح",
                "تداول",
                "فوركس",
                "محفظه استثمار",
                "مضاعفه",
            ),
        ),
    ),
    "fake_job": (
        (
            _g(
                "job",
                "jobs",
                "hiring",
                "vacancy",
                "recruiter",
                "employment",
                "work from home",
                "وظيف",
                "توظيف",
                "فرصه عمل",
                "عرض عمل",
                "عرض وظيف",
                "مقابله",
                "دوام",
            ),
            _g(
                "offer",
                "fee",
                "pay",
                "scam",
                "fake",
                "real",
                "genuine",
                "message",
                "email",
                "عرض",
                "رسوم",
                "نصب",
                "مزيف",
                "حقيقي",
                "دفع",
                "رساله",
                "مسج",
                "وصلني",
                "ارسل",
                "تطلب",
                "يطلب",
                "صدق",
            ),
        ),
    ),
    "online_shop": (
        (
            _g(
                "shop",
                "shopping",
                "store",
                "buy",
                "buying",
                "purchase",
                "seller",
                "cheap",
                "discount",
                "price",
                "sale",
                "تسوق",
                "شراء",
                "اشتري",
                "متجر",
                "بائع",
                "رخيص",
                "خصم",
                "سعر",
                "تخفيضات",
                "اشتريت",
            ),
            _g(
                "fake",
                "scam",
                "trust",
                "real",
                "genuine",
                "legit",
                "too good",
                "trap",
                "مزيف",
                "نصب",
                "موثوق",
                "حقيقي",
                "فخ",
                "اثق",
                "مضمون",
                "صدق",
                "امان",
            ),
        ),
    ),
    "report": (
        (_g("report", "complain", "complaint", "بلغ", "ابلغ", "اشتكي", "اشتكى", "شكوى", "بلاغ", "شكوي", "ابلاغ"),),
    ),
    "spot_scam": (
        (
            _g(
                "how to spot",
                "how do i spot",
                "how can i spot",
                "how to tell",
                "how do i know",
                "how to recognize",
                "how to recognise",
                "how to identify",
                "signs of",
                "warning signs",
                "red flag",
                "how can i tell",
                "كيف اعرف",
                "كيف اميز",
                "علامات",
                "كيف افرق",
                "كيف اكتشف",
                "شلون اعرف",
                "شلون اميز",
                "كيف اتعرف",
                "كيف اتاكد",
                "شلون اتاكد",
                "شلون افرق",
            ),
            _g("scam", "fraud", "phishing", "fake", "نصب", "احتيال", "نصاب", "مزيف", "رساله", "مسج", "وهمي"),
        ),
    ),
    "otp": (
        (
            _g("otp", "one time", "verification code", "security code", "pin", "code", "رمز", "كود"),
            _g(
                "bank",
                "ask",
                "share",
                "give",
                "send",
                "tell",
                "بنك",
                "يطلب",
                "يسال",
                "اعط",
                "ارسل",
                "اشارك",
                "اقول",
                "طلب",
                "يبي",
                "يبغي",
                "يرسل",
            ),
        ),
    ),
}
FAQ_ORDER: tuple[str, ...] = tuple(RULES)


def match_rules(command: str) -> str | None:
    """The FAQ name whose keyword rule fires first (rules are ordered most specific first), or None."""
    norm = normalise(command)
    toks = norm.split()
    if not toks:
        return None
    for name in FAQ_ORDER:
        for alt in RULES[name]:
            if all(_hit(norm, toks, g) for g in alt):
                return name
    return None


# --- prompt injection ---------------------------------------------------------------------------------

_INJECTION: tuple[str, ...] = tuple(
    _n(p)
    for p in (
        "ignore your", "ignore all", "ignore previous", "ignore the previous", "ignore prior", "ignore above",
        "disregard", "forget your", "forget all", "forget previous", "forget everything", "system prompt",
        "your instructions", "your rules", "your prompt", "you are now", "pretend", "act as", "roleplay",
        "role play", "developer mode", "jailbreak", "dan mode", "do anything now", "reveal your", "show your prompt",
        "new instructions", "override", "bypass", "sudo", "from now on",
        "تجاهل", "تجاهلي", "انسى تعليمات", "انس تعليمات", "انسى كل", "تعليماتك", "تعليمات النظام", "اوامرك",
        "تصرف كانك", "تصرف كأنك", "انت الان", "تظاهر", "العب دور", "وضع المطور", "كسر الحماية", "من الان",
        "اكشف تعليمات", "اظهر تعليماتك", "تخطى",
    )
)  # fmt: skip


def is_injection(command: str) -> bool:
    """Instruction-override attempts. Never obeyed: the utterance becomes `off_topic` (a fixed polite redirect)."""
    norm = normalise(command)
    return any(p in norm for p in _INJECTION)
