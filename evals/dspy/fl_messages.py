"""Template-generated INVENTED scam / legitimate messages for the script-classifier DSPy run.

PROVENANCE (read this before quoting a number): there is no supervisor-approved message dataset yet
(qwen-msg-001 was REJECTED in reviews/QWEN-qwen-msg-001.md; qwen-msg-002 has no review). Until one is approved
and dropped into `evals/dspy/approved_messages.jsonl` (same item schema), the classifier is optimised on this
deterministic template set. It is synthetic and labelled so everywhere (`synthetic: true`). It uses only the
fictional "Falcon Demo Bank", generic courier / authority names, `example[.]test` links and no phone numbers.
Validation templates are never seen in training (split by template, not by slot values).
Numbers on this set are optimistic compared with real traffic and must not be quoted as detection quality.
"""

from __future__ import annotations

import random
from typing import Any

BANK_EN, BANK_AR, BANK_AZ = "Falcon Demo Bank", "بنك فالكون التجريبي", "Falcon Demo Bank"
# (category, language) -> three templates. Slots: {amt} {code} {link}
T: dict[tuple[str, str], list[str]] = {}


def _add(cat: str, lang: str, *texts: str) -> None:
    assert len(texts) == 3
    T[(cat, lang)] = list(texts)


_add(
    "urgency",
    "en",
    "Your account will be suspended within 2 hours. Verify now to keep access: {link}",
    "FINAL NOTICE: your service is blocked today unless you confirm your details at {link}",
    "Action required immediately, your profile expires tonight. Update here {link}",
)
_add(
    "urgency",
    "msa",
    "سيتم إيقاف حسابك خلال ساعتين. يرجى التحقق الآن للمحافظة على الخدمة: {link}",
    "إشعار أخير: سيتم تعليق خدمتك اليوم ما لم تؤكد بياناتك عبر {link}",
    "مطلوب إجراء عاجل، تنتهي صلاحية ملفك الليلة. قم بالتحديث من هنا {link}",
)
_add(
    "urgency",
    "gulf",
    "حسابك بينوقف بعد ساعتين، سوي تحقق الحين عشان ما تخسر الخدمة {link}",
    "تنبيه اخير وايد مستعجل، خدمتك بتتعطل اليوم لو ما أكدت بياناتك {link}",
    "لازم تحدث ملفك الليلة قبل لا ينتهي، يالله ادخل {link}",
)
_add(
    "urgency",
    "arabizi",
    "7sabak rah yenwaqef b3d sa3tain, ta2akad el7een 3shan ma tkhsar el khedma {link}",
    "tanbeeh akheer, khedmtak btet3atal el yom lw ma akadt bayanatak {link}",
    "lazem tdawwer malafak el layla qabl ma yentahi, ydkhul {link}",
)

_add(
    "fake_fine",
    "en",
    "Traffic Authority: unpaid fine of AED {amt}. Pay today to avoid a doubled penalty: {link}",
    "You have an outstanding municipality fine (AED {amt}). Settle online now {link}",
    "Notice of violation, AED {amt} due. Late payment adds charges, pay at {link}",
)
_add(
    "fake_fine",
    "msa",
    "هيئة المرور: لديك مخالفة غير مسددة بقيمة {amt} درهم. سدد اليوم لتجنب مضاعفة الغرامة: {link}",
    "لديك مخالفة بلدية مستحقة ({amt} درهم). سدد المبلغ إلكترونيا الآن {link}",
    "إشعار مخالفة، المبلغ المستحق {amt} درهم. التأخر يضيف رسوما، السداد عبر {link}",
)
_add(
    "fake_fine",
    "gulf",
    "المرور: عليك مخالفة ما انسددت {amt} درهم، سددها اليوم قبل لا تتضاعف {link}",
    "عليك مخالفة بلدية ({amt} درهم) سددها الحين من هنا {link}",
    "وصلك مخالفة {amt} درهم، لو تأخرت بتزيد الغرامة، ادفع {link}",
)
_add(
    "fake_fine",
    "arabizi",
    "el moror: 3lek mokhalafa ma insaddat {amt} dirham, sadedha el yom qabl ma tt3adaf {link}",
    "3lek mokhalafa baladiya ({amt} dirham) sadedha el7een {link}",
    "wsalak mokhalafa {amt} dirham, lw t2akharet btzeed el gharama, edfa3 {link}",
)

_add(
    "delivery_fee",
    "en",
    "Generic Courier: your parcel is on hold. Pay a redelivery fee of AED {amt} here: {link}",
    "Parcel could not be delivered. Small customs fee AED {amt} required: {link}",
    "Your package is waiting at our depot, confirm address and pay AED {amt} {link}",
)
_add(
    "delivery_fee",
    "msa",
    "شركة التوصيل: شحنتك معلقة. يرجى دفع رسوم إعادة التوصيل {amt} درهم عبر {link}",
    "تعذر تسليم الطرد. مطلوب رسوم جمركية بسيطة {amt} درهم: {link}",
    "طردك ينتظر في المستودع، أكد العنوان وادفع {amt} درهم {link}",
)
_add(
    "delivery_fee",
    "gulf",
    "شركة التوصيل: شحنتك واقفة عندنا، ادفع {amt} درهم رسوم إعادة التوصيل {link}",
    "ما قدرنا نوصل الطرد، لازم تدفع رسوم جمارك {amt} درهم {link}",
    "طردك في المستودع، أكد عنوانك وادفع {amt} درهم زين {link}",
)
_add(
    "delivery_fee",
    "arabizi",
    "shirkat el tawseel: shehnatak wa2fa 3indna, edfa3 {amt} dirham rasm e3adat el tawseel {link}",
    "ma qdarna nwassel el tard, lazem tedfa3 rasm jamarek {amt} dirham {link}",
    "tardak fi el mustawda3, akkid 3enwanak w edfa3 {amt} dirham {link}",
)

_add(
    "bank_otp",
    "en",
    "Falcon Demo Bank security: suspicious login blocked. Reply with the OTP {code} or enter your card details at {link}",
    "Falcon Demo Bank: to cancel a payment of AED {amt} send us the code you just received and your card number {link}",
    "Your Falcon Demo Bank card is locked. Confirm your PIN and the one-time code to unlock: {link}",
)
_add(
    "bank_otp",
    "msa",
    "أمن بنك فالكون التجريبي: تم حظر محاولة دخول مشبوهة. أرسل رمز التحقق {code} أو أدخل بيانات بطاقتك عبر {link}",
    "بنك فالكون التجريبي: لإلغاء دفعة بقيمة {amt} درهم أرسل الرمز الذي وصلك ورقم بطاقتك {link}",
    "تم قفل بطاقتك في بنك فالكون التجريبي. أكد الرقم السري ورمز التحقق لفتحها: {link}",
)
_add(
    "bank_otp",
    "gulf",
    "بنك فالكون التجريبي: صار دخول مشبوه، ارسل لنا رمز التحقق {code} او ادخل بيانات بطاقتك {link}",
    "عشان نلغي عملية {amt} درهم ارسل الرمز اللي وصلك مع رقم البطاقة {link}",
    "بطاقتك انقفلت في بنك فالكون التجريبي، حط الرقم السري والرمز عشان تفتح {link}",
)
_add(
    "bank_otp",
    "arabizi",
    "Falcon Demo Bank: sar dkhool mashbooh, ersel lana ramz el ta7aqoq {code} aw adkhel bayanat betaqtak {link}",
    "3shan nelghi 3amaliya {amt} dirham ersel el ramz elli wsalak ma3 raqam el betaqa {link}",
    "betaqtak engafalat fi Falcon Demo Bank, 7ot el raqam el serri w el ramz 3shan tefta7 {link}",
)

_add(
    "digital_id_impersonation",
    "en",
    "Your national digital ID is about to be deactivated. Re-verify your identity with a photo of your ID: {link}",
    "Identity Authority: your residency record needs renewal today, upload your ID and selfie at {link}",
    "Digital ID alert: unusual sign-in. Confirm your identity number to avoid a lock {link}",
)
_add(
    "digital_id_impersonation",
    "msa",
    "سيتم تعطيل هويتك الرقمية قريبا. أعد التحقق من هويتك بصورة عن بطاقتك: {link}",
    "هيئة الهوية: سجل إقامتك يحتاج إلى تجديد اليوم، ارفع صورة الهوية وصورة شخصية عبر {link}",
    "تنبيه الهوية الرقمية: تسجيل دخول غير معتاد. أكد رقم هويتك لتجنب الإيقاف {link}",
)
_add(
    "digital_id_impersonation",
    "gulf",
    "هويتك الرقمية بتنوقف، رجع وثق هويتك وارفع صورة البطاقة {link}",
    "هيئة الهوية: اقامتك تبي تجديد اليوم، ارفع صورة الهوية وسيلفي هنا {link}",
    "تنبيه هويتك الرقمية: دخول غريب، أكد رقم هويتك قبل لا تنقفل {link}",
)
_add(
    "digital_id_impersonation",
    "arabizi",
    "hawiyatak el raqmiya rah tentawqef, a3ed tawtheeq w erfa3 soorat el betaqa {link}",
    "hay2at el hawiya: iqamtak tbi tajdeed el yom, erfa3 soorat el hawiya w selfie {link}",
    "tanbeeh el hawiya el raqmiya: dkhool ghareeb, akkid raqam hawiyatak qabl ma tenqafel {link}",
)

_add(
    "prize",
    "en",
    "Congratulations! You won AED {amt}00 in our monthly draw. Claim your prize now: {link}",
    "You have been selected for a free gift card. Pay AED {amt} shipping to receive it {link}",
    "Lucky winner! Confirm your details within 24 hours to collect your reward {link}",
)
_add(
    "prize",
    "msa",
    "مبروك! ربحت {amt}00 درهم في السحب الشهري. استلم جائزتك الآن: {link}",
    "تم اختيارك للحصول على بطاقة هدية مجانية. ادفع {amt} درهم رسوم الشحن لاستلامها {link}",
    "أنت الفائز المحظوظ! أكد بياناتك خلال 24 ساعة لاستلام مكافأتك {link}",
)
_add(
    "prize",
    "gulf",
    "مبروك ربحت {amt}00 درهم في السحب الشهري، استلم جايزتك الحين {link}",
    "انت مختار تاخذ بطاقة هدية مجانية، بس ادفع {amt} درهم شحن {link}",
    "يا حظك فزت! أكد بياناتك خلال 24 ساعة عشان تاخذ مكافأتك {link}",
)
_add(
    "prize",
    "arabizi",
    "mabrook! rbe7et {amt}00 dirham fi el sa7b el shahri, estlem jaytak el7een {link}",
    "enta mokhtar t5od betaqat hadiya majjaniya, bas edfa3 {amt} dirham shahn {link}",
    "ya 7azzak fezt! akkid bayanatak khelal 24 sa3a 3shan t5od mokafatak {link}",
)

_add(
    "job",
    "en",
    "Remote job, earn AED {amt}0 per day from home. Pay a registration fee of AED {amt} to start: {link}",
    "We reviewed your CV and you are hired. Send a deposit of AED {amt} for your work kit {link}",
    "Part-time offer, easy tasks, high pay. Message us and pay the onboarding fee {link}",
)
_add(
    "job",
    "msa",
    "وظيفة عن بعد، اربح {amt}0 درهم يوميا من المنزل. ادفع رسوم تسجيل {amt} درهم للبدء: {link}",
    "راجعنا سيرتك الذاتية وتم قبولك. أرسل وديعة {amt} درهم لحقيبة العمل {link}",
    "عرض عمل بدوام جزئي، مهام سهلة وأجر مرتفع. راسلنا وادفع رسوم الانضمام {link}",
)
_add(
    "job",
    "gulf",
    "وظيفة من البيت، تربح {amt}0 درهم باليوم، ادفع رسوم تسجيل {amt} درهم وابدأ {link}",
    "شفنا سيرتك الذاتية وانقبلت، حول وديعة {amt} درهم لشنطة الشغل {link}",
    "شغل جزئي سهل وراتبه حلو، كلمنا وادفع رسوم الانضمام {link}",
)
_add(
    "job",
    "arabizi",
    "waDheefa men el beit, terba7 {amt}0 dirham bel yom, edfa3 rasm tasjeel {amt} dirham w ebda2 {link}",
    "shefna el CV tabe3ak w enqabalt, 7awwel wadee3a {amt} dirham l shantat el shoghl {link}",
    "shoghl jozei sahl w ratebo 7elo, kallemna w edfa3 rasm el enDemam {link}",
)

_add(
    "investment",
    "en",
    "Guaranteed 40% monthly returns on crypto. Deposit AED {amt}00 today, limited seats: {link}",
    "Join our private trading group, double your money in 7 days with zero risk {link}",
    "Insider tip: invest AED {amt}0 now and withdraw triple next week {link}",
)
_add(
    "investment",
    "msa",
    "عوائد مضمونة 40% شهريا على العملات الرقمية. أودع {amt}00 درهم اليوم، المقاعد محدودة: {link}",
    "انضم إلى مجموعة التداول الخاصة وضاعف أموالك خلال 7 أيام دون مخاطر {link}",
    "نصيحة داخلية: استثمر {amt}0 درهما الآن واسحب ثلاثة أضعاف الأسبوع القادم {link}",
)
_add(
    "investment",
    "gulf",
    "ارباح مضمونة 40% كل شهر بالكريبتو، حط {amt}00 درهم اليوم والمقاعد قليلة {link}",
    "ادخل قروب التداول الخاص وضاعف فلوسك في 7 ايام بدون خسارة {link}",
    "معلومة من الداخل: استثمر {amt}0 درهم الحين واسحب ثلاثة اضعافها الاسبوع الجاي {link}",
)
_add(
    "investment",
    "arabizi",
    "arba7 madmoona 40% kol shahr bel crypto, 7ot {amt}00 dirham el yom w el maqa3ed qaleela {link}",
    "edkhol group el trading el khass w da3ef floosak fi 7 ayyam bdoon khasara {link}",
    "ma3looma men el dakhel: estathmer {amt}0 dirham el7een w es7ab talat adaa3ha el esboo3 el jay {link}",
)

# Legitimate look-alikes ("none"): same vocabulary (codes, fees, deadlines, links) but no scam ask.
_add(
    "none",
    "en",
    "Falcon Demo Bank: your one-time code is {code}. Never share it with anyone, we will never ask for it.",
    "Reminder: your appointment is tomorrow at 10:30. Reply C to confirm or R to reschedule.",
    "Receipt: your payment of AED {amt} was received. Thank you. Details are in the app.",
)
_add(
    "none",
    "msa",
    "بنك فالكون التجريبي: رمز التحقق الخاص بك هو {code}. لا تشاركه مع أحد، ولن نطلبه منك أبدا.",
    "تذكير: موعدك غدا الساعة 10:30. أرسل C للتأكيد أو R لتغيير الموعد.",
    "إيصال: تم استلام دفعتك بقيمة {amt} درهم. شكرا لك. التفاصيل في التطبيق.",
)
_add(
    "none",
    "gulf",
    "بنك فالكون التجريبي: رمزك {code}، لا تعطيه احد ولا نسألك عنه ابدا.",
    "تذكير بموعدك بكرة الساعة 10:30، رد C للتأكيد او R نغير الموعد.",
    "وصلنا دفعتك {amt} درهم، مشكور. التفاصيل في التطبيق.",
)
_add(
    "none",
    "arabizi",
    "Falcon Demo Bank: ramzak howa {code}, la tshaarko ma3 ay a7ad w ma ra7 nes2alak 3anno abadan.",
    "tathkeer b maw3edak bukra el sa3a 10:30, rod C lel ta2keed aw R lel taghyeer.",
    "wsalatna dafa3tak {amt} dirham, mashkoor. el tafaseel fi el application.",
)

CATEGORIES = tuple(dict.fromkeys(c for c, _ in T))
LANGUAGES = ("en", "msa", "gulf", "arabizi")
AMOUNTS = ("5", "9", "12", "25", "35", "49", "75", "150")


def build_messages(seed: int = 20261122, variants_per_template: int = 3) -> list[dict[str, Any]]:
    """Deterministic: same seed -> byte-identical list. `template` is the group key used for the split."""
    rng = random.Random(seed)
    items: list[dict[str, Any]] = []
    for (cat, lang), templates in sorted(T.items()):
        for ti, tpl in enumerate(templates):
            seen: set[str] = set()
            for _ in range(variants_per_template * 4):
                if len(seen) >= variants_per_template:
                    break
                text = tpl.format(
                    amt=rng.choice(AMOUNTS),
                    code=f"{rng.randrange(100000, 999999)}",
                    link=f"hxxps://example[.]test/{rng.choice('abcdefghjkmnpqrstuvwxyz')}{rng.randrange(100, 999)}",
                )
                if text in seen:
                    continue
                seen.add(text)
                items.append(
                    {
                        "id": f"msg-{cat}-{lang}-{ti}-{len(seen)}",
                        "text": text,
                        "category": cat,
                        "is_scam": cat != "none",
                        "language": lang,
                        "template": f"{cat}/{lang}/{ti}",
                        "synthetic": True,
                    }
                )
    return items
