"""Labelled synthetic fixture corpus for the gap evals (invented brand "Falcon Demo Bank", reserved hosts only).

Everything here is SYNTHETIC: pages carry a visible "TEST FIXTURE, not a real site" label and have no live
counterpart; hosts end in ``.test`` (RFC 6761); messages are written for this suite and say so. Labels
(``phish`` and the expected extractor fields) are assigned by the author at write time, before any model ran.
Nothing is ever fetched from the network and no real brand, logo or domain appears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

OFFICIAL_HOST = "falcon-demo-bank.test"
BANNER = '<h1 style="background:#c00;color:#fff;padding:1rem">TEST FIXTURE, not a real site</h1>'


@dataclass(frozen=True)
class Expect:
    """Expected extractor fields. ``requested`` is a set; ``brand`` None means 'no brand claimed'."""

    brand: str | None
    requested: frozenset[str]
    script: str
    lang: str


@dataclass(frozen=True)
class Item:
    item_id: str
    kind: str  # page | message
    phish: bool
    expect: Expect
    url: str | None = None
    html: str | None = None
    text: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


def page_html(
    title: str, heading: str, paragraph: str, fields: tuple[tuple[str, str], ...] = (), lang: str = "en"
) -> str:
    """A fixture page. ``fields`` are (label, input type); the form posts nowhere."""
    rows = "".join(
        f'<label>{escape(lbl)} <input name="f{i}" type="{typ}" autocomplete="off"></label>\n'
        for i, (lbl, typ) in enumerate(fields)
    )
    form = (
        f'<form action="#" method="post" onsubmit="return false">\n{rows}'
        '<button type="button" disabled>Disabled: this form posts nowhere</button></form>'
        if fields
        else ""
    )
    d = "rtl" if lang == "ar" else "ltr"
    return (
        f'<!doctype html><html lang="{lang}" dir="{d}"><head><meta charset="utf-8">'
        f'<meta name="robots" content="noindex, nofollow"><title>TEST FIXTURE - {escape(title)}</title></head>'
        f"<body>{BANNER}<h2>{escape(heading)}</h2><p>{escape(paragraph)}</p>{form}</body></html>"
    )


def _e(brand: str | None, requested: tuple[str, ...], script: str, lang: str) -> Expect:
    return Expect(brand, frozenset(requested), script, lang)


FDB = "falcon_demo_bank"
LOOK = "falcon-demo-bank-secure-login.test"


def _items() -> list[Item]:
    out: list[Item] = []
    # --- pages -----------------------------------------------------------------------------------------
    out += [
        Item(
            "pg-official-login",
            "page",
            False,
            _e(FDB, ("password",), "none", "en"),
            url=f"https://{OFFICIAL_HOST}/login",
            html=page_html(
                "Falcon Demo Bank sign in",
                "Falcon Demo Bank | بنك الصقر التجريبي",
                "Sign in to Falcon Demo Bank online banking to continue.",
                (("Username", "text"), ("Password", "password")),
            ),
            tags=("official",),
        ),
        Item(
            "pg-look-verify-en",
            "page",
            True,
            _e(FDB, ("password", "otp"), "account_verification", "en"),
            url=f"https://{LOOK}/verify",
            html=page_html(
                "Falcon Demo Bank account verification",
                "Falcon Demo Bank: verify your account",
                "Your account is limited. Enter your password and the one-time code sent to your phone to restore access.",  # noqa: E501
                (("Password", "password"), ("One-time code", "text")),
            ),
            tags=("lookalike",),
        ),
        Item(
            "pg-look-card-en",
            "page",
            True,
            _e(FDB, ("card_number", "card_cvv"), "account_verification", "en"),
            url="https://falcon-demo-bank-cards.test/update",
            html=page_html(
                "Falcon Demo Bank card update",
                "Falcon Demo Bank: update your payment card",
                "Your card expires today. Enter the card number and the security code to keep using it.",
                (("Card number", "text"), ("CVV", "password")),
            ),
            tags=("lookalike",),
        ),
        Item(
            "pg-look-verify-ar",
            "page",
            True,
            _e(FDB, ("password", "otp"), "account_verification", "ar"),
            url="https://falcon-dem0-bank.test/ar/verify",
            html=page_html(
                "بنك الصقر التجريبي",
                "بنك الصقر التجريبي: تأكيد الحساب",
                "تم تقييد حسابك. أدخل كلمة المرور ورمز التحقق المرسل إلى هاتفك لاستعادة الوصول.",
                (("كلمة المرور", "password"), ("رمز التحقق", "text")),
                lang="ar",
            ),
            tags=("lookalike", "arabic"),
        ),
        Item(
            "pg-look-prize-en",
            "page",
            True,
            _e(FDB, ("bank_account",), "prize_lottery", "en"),
            url="https://falcon-demo-bank-rewards.test/win",
            html=page_html(
                "Falcon Demo Bank rewards",
                "Falcon Demo Bank customer prize draw",
                "You have won a prize. Enter your bank account number so we can send it to you.",
                (("Account number", "text"),),
            ),
            tags=("lookalike",),
        ),
        Item(
            "pg-generic-login",
            "page",
            True,
            _e(None, ("password",), "account_verification", "en"),
            url="https://account-review-portal.test/start",
            html=page_html(
                "Account review",
                "Account review required",
                "Confirm your identity to avoid suspension. Enter your username and password.",
                (("Username", "text"), ("Password", "password")),
            ),
            tags=("generic",),
        ),
        Item(
            "pg-benign-events",
            "page",
            False,
            _e(None, (), "none", "en"),
            url="https://community-garden-club.test/events",
            html=page_html(
                "Community Garden Club events",
                "Community Garden Club",
                "Join us on Saturday morning to plant herbs. Bring a hat and water. All welcome, no sign-up needed.",
            ),
            tags=("benign",),
        ),
        Item(
            "pg-benign-ar",
            "page",
            False,
            _e(None, (), "none", "ar"),
            url="https://neighbourhood-library.test/ar",
            html=page_html(
                "مكتبة الحي",
                "مكتبة الحي",
                "تفتح المكتبة أبوابها من التاسعة صباحاً حتى الخامسة مساءً. يمكنكم استعارة ثلاثة كتب لمدة أسبوعين.",
                lang="ar",
            ),
            tags=("benign", "arabic"),
        ),
        Item(
            "pg-benign-recipe",
            "page",
            False,
            _e(None, (), "none", "en"),
            url="https://slow-cooking-notes.test/lentil-soup",
            html=page_html(
                "Lentil soup",
                "Lentil soup",
                "Rinse the lentils, simmer with onion, cumin and a little lemon for thirty minutes, then blend.",
            ),
            tags=("benign",),
        ),
        Item(
            "pg-benign-newsletter",
            "page",
            False,
            _e(None, (), "none", "en"),
            url="https://town-bike-club.test/newsletter",
            html=page_html(
                "Bike club newsletter",
                "Town Bike Club newsletter",
                "This month: a sunrise ride, a repair workshop and a charity ride route map. Read the full notes below.",  # noqa: E501
            ),
            tags=("benign",),
        ),
    ]
    # --- messages --------------------------------------------------------------------------------------
    P = "TEST MESSAGE (synthetic). "
    PA = "رسالة تجريبية (اصطناعية). "
    msgs: list[tuple[str, bool, Expect, str, tuple[str, ...]]] = [
        (
            "msg-bank-otp-en",
            True,
            _e(FDB, ("password", "otp"), "account_verification", "en"),
            P
            + "Falcon Demo Bank: your account is locked. Reply with your password and the OTP code we texted you to unlock it.",  # noqa: E501
            ("scam",),
        ),
        (
            "msg-bank-otp-ar",
            True,
            _e(FDB, ("password", "otp"), "account_verification", "ar"),
            PA + "بنك الصقر التجريبي: تم إيقاف حسابك. أرسل كلمة المرور ورمز التحقق الذي وصلك لإعادة تفعيله.",
            ("scam", "arabic"),
        ),
        (
            "msg-delivery-en",
            True,
            _e(None, ("payment", "card_number"), "delivery_fee", "en"),
            P
            + "Your parcel is on hold. Pay the small delivery fee with your card number today or it will be returned.",
            ("scam",),
        ),
        (
            "msg-fine-ar",
            True,
            _e(None, ("payment",), "traffic_fine", "ar"),
            PA + "لديك مخالفة مرورية غير مدفوعة. يرجى سداد الغرامة خلال 24 ساعة لتجنب مضاعفتها.",
            ("scam", "arabic"),
        ),
        (
            "msg-prize-en",
            True,
            _e(None, ("bank_account",), "prize_lottery", "en"),
            P + "Congratulations, you won our prize draw! Send your bank account number to receive the money.",
            ("scam",),
        ),
        (
            "msg-job-ar",
            True,
            _e(None, ("emirates_id",), "job_offer", "ar"),
            PA + "فرصة عمل من المنزل براتب مرتفع. أرسل صورة هويتك الإماراتية للتسجيل اليوم.",
            ("scam", "arabic"),
        ),
        (
            "msg-invest-en",
            True,
            _e(None, ("payment",), "investment", "en"),
            P + "Double your savings in 7 days with guaranteed returns. Transfer your first payment now to join.",
            ("scam",),
        ),
        (
            "msg-techsupport-en",
            True,
            _e(None, ("remote_access_app",), "tech_support", "en"),
            P + "Your computer has a virus. Install the remote access app so our technician can fix it for you now.",
            ("scam",),
        ),
        (
            "msg-card-mixed",
            True,
            _e(FDB, ("card_cvv",), "account_verification", "mixed"),
            P + "عزيزي العميل, your Falcon Demo Bank card is blocked. Send the CVV code on the back to reactivate it.",
            ("scam", "arabic"),
        ),
        (
            "msg-charity-en",
            True,
            _e(None, ("payment",), "charity", "en"),
            P + "Help families in need this week. Please transfer your donation today, every amount counts.",
            ("scam",),
        ),
        (
            "msg-benign-lunch",
            False,
            _e(None, (), "none", "en"),
            P + "Hi, are we still meeting for lunch tomorrow at one? I will book a table near the office.",
            ("benign",),
        ),
        (
            "msg-benign-ar",
            False,
            _e(None, (), "none", "ar"),
            PA + "هل ننسق موعد الاجتماع غداً الساعة العاشرة صباحاً؟ أخبرني إذا كان الوقت مناسباً.",
            ("benign", "arabic"),
        ),
        (
            "msg-benign-arabizi",
            False,
            _e(None, (), "none", "arabizi"),
            P + "marhaba, kefak? bukra nrooh el sahra ma3 el shabab, 2ool lee law inta jaay.",
            ("benign",),
        ),
        (
            "msg-benign-statement",
            False,
            _e(FDB, (), "none", "en"),
            P
            + "Falcon Demo Bank: your monthly statement is ready in the app. We never ask for your password or codes.",
            ("benign",),
        ),
    ]
    for iid, phish, ex, text, tags in msgs:
        out.append(Item(iid, "message", phish, ex, text=text, tags=tags))
    return out


ITEMS: tuple[Item, ...] = tuple(_items())


def hosts(items: tuple[Item, ...] = ITEMS) -> set[str]:
    out = set()
    for it in items:
        if it.url:
            out.add(it.url.split("/")[2])
    return out


# --- brand-new lookalike set (item 7) ------------------------------------------------------------------------
# Hosts invented for this suite; none is in any feed, in the training data or in the brand registry.
# phishing=True: a lookalike or a generic credential page on a never-seen host. phishing=False: controls.
NEW_LOOKALIKE_HOSTS: tuple[tuple[str, str], ...] = (
    ("falcon-dem0-bank-login.test", "typosquat"),
    ("falcon-demo-bnak.test", "typosquat"),
    ("falcondemobank-secure.test", "combosquat"),
    ("falcon-demo-bank-verify.test", "combosquat"),
    ("secure-falcon-demo-bank.test", "combosquat"),
    ("falcon-demo-bank-support.test", "combosquat"),
    ("login.falcon-demo-bank.account-check.test", "subdomain"),
    ("falcon-demo-bank.signin-portal.test", "subdomain"),
    ("online-falcon-demo-bank.test", "combosquat"),
    ("falcon-demo-bank-update.test", "combosquat"),
    ("falconn-demo-bank.test", "typosquat"),
    ("falcon-dernobank.test", "typosquat"),
)
NEW_GENERIC_HOSTS: tuple[str, ...] = (
    "account-review-center.test",
    "secure-id-check.test",
    "customer-update-desk.test",
    "verify-my-profile.test",
    "service-restore-now.test",
    "member-access-help.test",
)
NEW_BENIGN_HOSTS: tuple[str, ...] = (
    "harbour-view-cafe.test",
    "city-chess-league.test",
    "pottery-weekend.test",
    "open-air-cinema.test",
    "kids-reading-corner.test",
    "desert-walks-guide.test",
    "tiny-kitchen-ideas.test",
    "local-bird-watchers.test",
)


def new_lookalike_set() -> list[Item]:
    """Phishing-like fixtures on hosts absent from every feed and the training data, plus benign controls."""
    out: list[Item] = []
    pats = [
        (
            "Falcon Demo Bank: verify your account",
            "Your account is limited. Enter your password and the code we sent you.",
            (("Password", "password"), ("One-time code", "text")),
        ),
        (
            "Falcon Demo Bank sign in",
            "Sign in to Falcon Demo Bank online banking to continue.",
            (("Username", "text"), ("Password", "password")),
        ),
    ]
    for i, (host, kind) in enumerate(NEW_LOOKALIKE_HOSTS):
        h, p, f = pats[i % 2]
        out.append(
            Item(
                f"new-look-{i:02d}",
                "page",
                True,
                _e(FDB, ("password",), "account_verification", "en"),
                url=f"https://{host}/login",
                html=page_html(h, h, p, f),
                tags=("new_lookalike", kind),
            )
        )
    for i, host in enumerate(NEW_GENERIC_HOSTS):
        out.append(
            Item(
                f"new-gen-{i:02d}",
                "page",
                True,
                _e(None, ("password",), "account_verification", "en"),
                url=f"https://{host}/start",
                html=page_html(
                    "Account review",
                    "Account review required",
                    "Confirm your identity to avoid suspension. Enter your username and password.",
                    (("Username", "text"), ("Password", "password")),
                ),
                tags=("new_generic",),
            )
        )
    for i, host in enumerate(NEW_BENIGN_HOSTS):
        out.append(
            Item(
                f"new-ben-{i:02d}",
                "page",
                False,
                _e(None, (), "none", "en"),
                url=f"https://{host}/",
                html=page_html(
                    "Local club", "Welcome", "Meeting times, a map and a short note about this week's activity."
                ),
                tags=("new_benign",),
            )
        )
    out.append(
        Item(
            "new-official-control",
            "page",
            False,
            _e(FDB, ("password",), "none", "en"),
            url=f"https://{OFFICIAL_HOST}/login",
            html=page_html(
                "Falcon Demo Bank sign in",
                "Falcon Demo Bank | بنك الصقر التجريبي",
                "Sign in to Falcon Demo Bank online banking to continue.",
                (("Username", "text"), ("Password", "password")),
            ),
            tags=("official",),
        )
    )
    return out
