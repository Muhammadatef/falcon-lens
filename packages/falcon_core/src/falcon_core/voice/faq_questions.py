"""The canonical question(s) behind each FAQ answer, in English and Arabic (Emirati and MSA).

Only used by the semantic fallback (faq_semantic.py): their embeddings are computed once at start and a spoken
question is matched to the nearest one. They are never spoken. Keys are the FAQ names of web/lib/voice-script.ts.
"""

from __future__ import annotations

QUESTIONS: dict[str, tuple[str, ...]] = {
    "otp": (
        "Does the bank ask for my one-time code?",
        "Should I give my verification code to someone who says he is from the bank?",
        "هل البنك يطلب مني رمز التحقق؟",
        "البنك يطلب مني الرمز اللي وصلني؟ أعطيه؟",
    ),
    "clicked_link": (
        "I already clicked the link, what should I do now?",
        "I opened a suspicious link by mistake",
        "ضغطت على الرابط، شو أسوي الحين؟",
        "فتحت رابط مشكوك فيه بالغلط، وش المفروض أسوي؟",
    ),
    "shared_card": (
        "I shared my card number with someone, what now?",
        "I gave my card details to a scammer",
        "أعطيت رقم بطاقتي لواحد، شو أسوي؟",
        "شاركت بيانات بطاقتي مع نصاب",
    ),
    "fake_police": (
        "Someone calls saying he is from the police and asks me for money",
        "A man claiming to be an officer threatens me with a fine unless I pay",
        "واحد يتصل ويقول إنه من الشرطة ويطلب مني فلوس",
        "اتصل علي شخص يقول ضابط ويهددني بغرامة إذا ما دفعت",
    ),
    "parcel_fee": (
        "I got a message asking me to pay a delivery fee for a parcel",
        "A courier text says my package is held until I pay a charge",
        "وصلتني رسالة توصيل طرد وتطلب رسوم",
        "مسج يقول طردي موقوف ولازم أدفع رسوم جمارك",
    ),
    "prize": (
        "I received a message that I won a prize in a lottery",
        "They say I won a draw I never entered",
        "وصلتني رسالة إني ربحت جايزة في سحب",
        "قالوا لي فزت في مسابقة وأنا ما شاركت",
    ),
    "investment": (
        "Someone offers me an investment with guaranteed profit in crypto",
        "Is a high-return trading offer a scam?",
        "واحد يعرض علي استثمار بأرباح مضمونة في العملات الرقمية",
        "عرض تداول بأرباح عالية، هل هو نصب؟",
    ),
    "fake_job": (
        "I got a job offer by message and they ask me to pay a fee first",
        "Is this job offer real or a scam?",
        "وصلني عرض وظيفة ويبون مني رسوم قبل لا أبدأ",
        "هل عرض الوظيفة هذا حقيقي ولا نصب؟",
    ),
    "report": (
        "How do I report a scam?",
        "Where can I file a complaint about fraud?",
        "كيف أبلغ عن عملية نصب؟",
        "وين أقدم بلاغ عن احتيال؟",
    ),
    "about": (
        "What is Falcon Lens and what does it do?",
        "Tell me about this app",
        "ما هي عدسة الصقر وايش تسوي؟",
        "عرفني على نفسك",
    ),
    "agents": (
        "Who are Baseer and Dir?",
        "What do the two agents do?",
        "من هم بصير ودرع؟",
        "شو شغل بصير وشو شغل درع؟",
    ),
    "data_stored": (
        "Is my data stored? Do you record my voice?",
        "Do you keep my messages?",
        "هل بياناتي تنحفظ؟ وهل تسجلون صوتي؟",
        "رسايلي وصوتي يتخزنون عندكم؟",
    ),
    "bank_link": (
        "My bank sent me a link to update my account details",
        "A message from the bank says my account is suspended, click here to verify",
        "البنك أرسل لي رابط عشان أحدث بياناتي",
        "وصلني مسج من البنك يقول حسابك موقوف اضغط الرابط",
    ),
    "friend_money": (
        "My friend messaged me on WhatsApp asking me to send money urgently",
        "A contact asks me to transfer money by message",
        "صديقي أرسل لي على الواتساب يطلب فلوس بسرعة",
        "واحد من ربعي يبي مني تحويل برسالة",
    ),
    "relative_urgent": (
        "Someone called saying my son had an accident and needs money now",
        "A caller says my relative is in trouble abroad and needs money",
        "اتصل واحد يقول ولدي سوا حادث ويحتاج فلوس الحين",
        "يقولون قريبي عالق في الخارج ويحتاج مبلغ عاجل",
    ),
    "remote_access": (
        "A caller asks me to install an app and share my screen",
        "Someone from support wants remote access to my phone",
        "واحد يتصل ويطلب مني أنزل برنامج وأشارك شاشتي",
        "موظف دعم يبي يتحكم في جهازي عن بعد",
    ),
    "qr_code": (
        "Is it safe to scan this QR code?",
        "Someone sent me a QR code to scan",
        "أمسح رمز الكيو آر هذا؟",
        "وصلني باركود وقالوا امسحه",
    ),
    "online_shop": (
        "Is this online shop real? The prices are very cheap",
        "Can I trust a website selling at a big discount?",
        "هذا المتجر الإلكتروني حقيقي؟ أسعاره رخيصة مرة",
        "أقدر أشتري من موقع يبيع بخصم كبير؟",
    ),
    "sent_money": (
        "I already transferred money to a scammer, what can I do?",
        "I paid a fraudster, can I get it back?",
        "حولت فلوس لنصاب، شو أسوي؟",
        "دفعت لواحد نصب عليّ، أقدر أرجعها؟",
    ),
    "shared_login": (
        "I gave my password to someone, what now?",
        "I typed my login details on a fake page",
        "أعطيت كلمة السر لواحد، شو أسوي؟",
        "دخلت بيانات الدخول في صفحة مزيفة",
    ),
    "spot_scam": (
        "How can I tell if a message is a scam?",
        "What are the warning signs of fraud?",
        "كيف أعرف إن الرسالة نصب؟",
        "شلون أميز رسالة الاحتيال؟",
    ),
    "limits": (
        "Are you always right? Can you make mistakes?",
        "How accurate are you?",
        "هل أنت دايماً صح؟ تغلط؟",
        "قد تخطئ في الحكم؟ كم دقتك؟",
    ),
}
