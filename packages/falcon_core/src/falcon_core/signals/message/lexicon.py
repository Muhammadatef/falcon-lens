# ruff: noqa: E501
"""Rule lexicons: Arabic (MSA + Gulf), English, Arabizi. Entries are regex fragments, run through the same
normaliser as the text (so write them with any alef/yaa/taa form). A rule is a list of groups; every group
must match (OR within a group). Generic terms only: no real brand names."""

from __future__ import annotations

Group = dict[str, list[str]]  # lang -> fragments

RULES: dict[str, list[Group]] = {
    "urgency": [
        {
            "ar": [
                "فورا",
                "عاجل",
                "حالا",
                "الحين",
                "بسرعة",
                "في اسرع وقت",
                "خلال \\d+ ساع",
                "قبل نهاية اليوم",
                "اخر فرصة",
                "اخر تنبيه",
                "اخر انذار",
                "سيتم (ايقاف|تعليق|حظر|الغاء|تجميد)",
                "بيتم (ايقاف|تعليق|حظر|الغاء)",
                "لا تتاخر",
            ],
            "en": [
                "urgent",
                "immediately",
                "within \\d+ ?(hours|hrs|h)",
                "act now",
                "last warning",
                "final notice",
                "expires? today",
                "will be (suspended|blocked|closed|frozen|cancell?ed)",
                "asap",
            ],
            "arz": ["3ajil", "3ajel", "fawran", "bsor3a", "bsur3a", "al7in", "akher tanbeeh", "akher fursa"],
        }
    ],
    "secrecy": [
        {
            "ar": [
                "لا ?تخبر",
                "لا ?تقول لاحد",
                "لا ?تبلغ احد",
                "لا ?تتكلم مع احد",
                "سري للغاية",
                "بسرية تامة",
                "لا ?تفتح فمك",
                "بيننا فقط",
                "لا تعلم احد",
                "لا ?تقل لاحد",
            ],
            "en": [
                "do not tell",
                "don'?t tell",
                "keep (this|it) (a )?(secret|confidential|private)",
                "do not inform",
                "between us",
                "tell no ?one",
                "do not discuss",
            ],
            "arz": ["la tkhbr", "la tgol", "la tqol", "la t2ol", "sirri", "sirriya", "bayni wabaynak"],
        }
    ],
    "otp_request": [
        {
            # an ASK: imperative verb + (up to a few words) + code noun. Delivery ("رمز التحقق هو ...") and
            # warnings ("لا تشارك الرمز") never match: the verb must start a word and must not be negated.
            "ar": [
                "(?<!لا )(?<!لا)(ارسل|ارسلي|ارسلوا|ابعث|زودنا|زودني|شاركنا|شارك|اخبرنا|اخبرني|اعطنا|اعطني|عطنا|قولنا|قل لنا|اذكر) "
                "[^.!?,]{0,30}?(الرمز|رمز|الكود|كود|رقم التحقق|كلمة المرور|كلمة السر|الرقم السري|cvv|otp)"
            ],
            "en": [
                "(?<!not )(?<!never )(?<!t )(send|share|tell|give|provide|read out|forward|reply with) "
                "[^.!?]{0,30}?(otp|code|pin|cvv|passcode|password)\\b"
            ],
            "arz": [
                "(?<!la )(?<!ma )(ersel|ersal|rsel|ab3at|ba3at|ab3ath|shareek|sheer|7ot|katab|ktb|2olli|oli) "
                "[^.!?]{0,25}?(code|kod|ramz|otp|pin|cvv|password)\\b"
            ],
        }
    ],
    "remote_access": [
        {
            "ar": [
                "انيديسك",
                "اني ديسك",
                "اني دسك",
                "تيم ?فيور",
                "كويك ?سابورت",
                "التحكم عن بعد",
                "الوصول عن بعد",
                "(حمل|نزل|ثبت) (تطبيق|برنامج)",
                "برنامج المساعدة",
            ],
            "en": [
                "any ?desk",
                "team ?viewer",
                "quick ?support",
                "ultra ?viewer",
                "rust ?desk",
                "remote (access|desktop|control|support)",
                "(install|download) (the |this )?(app|application|software)",
            ],
            "arz": [
                "any ?desk",
                "team ?viewer",
                "7ml barnamaj",
                "hamil barnamaj",
                "nazzel barnamaj",
                "nazel barnameg",
                "tahmeel barnamaj",
            ],
        }
    ],
    "payment": [
        {
            "ar": [
                "ادفع",
                "سدد",
                "قم بالدفع",
                "رابط الدفع",
                "تحويل (مبلغ|بنكي)",
                "حول (مبلغ|المبلغ)",
                "حوالة",
                "بيانات (البطاقة|بطاقتك)",
                "رقم البطاقة",
                "ايبان",
                "iban",
                "تحديث بيانات",
                "عملة رقمية",
                "usdt",
            ],
            "en": [
                "pay (now|the|your|within)",
                "payment",
                "wire (the )?(money|funds)",
                "transfer (the )?(money|funds|amount)",
                "card (details|number)",
                "iban",
                "gift ?cards?",
                "usdt",
            ],
            "arz": [
                "idfa3",
                "idfa'?a",
                "sadid",
                "7awel",
                "7awala",
                "raqam el ?bitaqa",
                "bayanat el ?bitaqa",
                "ta7weel",
            ],
        }
    ],
    "authority": [
        {
            # strong entities, or a first-person claim ("معك / this is / calling from") before an entity.
            # A bare «بنك» / "bank" is NOT a claim.
            "ar": [
                "شرطة",
                "وزارة الداخلية",
                "النيابة",
                "المحكمة",
                "الهوية والجنسية",
                "الهيئة الاتحادية",
                "المصرف المركزي",
                "الادارة العامة للاقامة",
                "الجرائم الالكترونية",
                "مكافحة الجرائم",
                "الامن السيبراني",
                "قسم الاحتيال",
                "(معك|معاك|معكم|انا|نحن|هنا|اتصل بك من|نتصل بك من|نتواصل معك من|اتواصل معك من|اتكلم معك من|اتحدث من|موظف|ممثل|ضابط|مندوب) "
                "[^.!?,]{0,25}?(بنك|مصرف|هيئة|دائرة|وزارة)",
            ],
            "en": [
                "police",
                "ministry of interior",
                "public prosecution",
                "central bank",
                "federal authority",
                "cyber ?crime",
                "court (order|case)",
                "customs authority",
                "bank (security|fraud) (team|department)",
                "fraud (department|team)",
                "(this is|i am|i'?m|we are|we'?re|calling from|speaking from|contacting you from|officer|agent|representative) "
                "[^.!?]{0,30}?\\b(bank|ministry|authority|department)\\b",
            ],
            "arz": [
                "shurta",
                "shortat",
                "wizarat el ?dakhiliya",
                "niyaba",
                "mahkama",
                "jara'?im",
                "(ma3ak|ana|ahna|7na|men|min|mn) (el |al |bel |bil )?bank\\b",
            ],
        }
    ],
    "prize": [
        {
            "ar": [
                "مبروك",
                "فزت",
                "ربحت",
                "انت (من )?الفائز",
                "الفائزين",
                "جائزة",
                "جايزة",
                "السحب على",
                "هدية مجانية",
                "كوبون",
                "مليون درهم",
            ],
            "en": [
                "congratulations",
                "you (have )?won",
                "winner",
                "prize",
                "lucky draw",
                "raffle",
                "free gift",
                "claim your",
            ],
            "arz": ["mabrook", "mabrouk", "fezt", "rabe7t", "rabaht", "jaeza", "ja2eza", "sa7b"],
        }
    ],
    "job": [
        {
            "ar": [
                "وظيفة",
                "وظائف",
                "فرصة عمل",
                "التوظيف",
                "مطلوب (موظفين|موظفات)",
                "عمل من المنزل",
                "دوام جزئي",
                "ارسل سيرتك",
                "راتب",
            ],
            "en": [
                "job offer",
                "vacanc(y|ies)",
                "we are hiring",
                "hiring",
                "work from home",
                "part[- ]time",
                "salary",
                "earn \\w+ ?(per|a|every) ?day",
            ],
            "arz": ["wazifa", "wadhifa", "fursat 3amal", "3amal min el ?bait", "raatib", "ratib"],
        }
    ],
    "investment": [
        {
            "ar": [
                "استثمار",
                "استثمر",
                "ارباح",
                "عوائد",
                "تداول",
                "عملات رقمية",
                "ربح مضمون",
                "ضاعف (اموالك|فلوسك)",
                "بيتكوين",
                "منصة تداول",
            ],
            "en": [
                "invest(ment|ing|or)?",
                "guaranteed (profit|returns?)",
                "trading platform",
                "crypto",
                "bitcoin",
                "forex",
                "double your money",
                "daily profit",
            ],
            "arz": ["istithmar", "estithmar", "arba7", "tadawul", "bitcoin"],
        }
    ],
    "delivery_fee": [
        {
            "ar": ["طرد", "شحنة", "شحنتك", "توصيل", "التوصيل", "بريد"],
            "en": ["parcel", "package", "shipment", "delivery", "courier"],
            "arz": ["tard", "shahna", "tawseel"],
        },
        {
            "ar": [
                "رسوم",
                "جمارك",
                "اعادة (الجدولة|التوصيل)",
                "تعذر",
                "عنوان (غير )?(مكتمل|ناقص)",
                "ادفع",
                "سدد",
            ],
            "en": [
                "fees?",
                "customs",
                "re-?deliver(y)?",
                "failed delivery",
                "address (incomplete|issue|not found)",
                "pay",
            ],
            "arz": ["rusoom", "rasm", "jamarik", "idfa3", "sadid"],
        },
    ],
    "fine": [
        {
            "ar": ["مخالفة", "مخالفات", "غرامة", "غرامات", "نقاط سوداء", "حجز (المركبة|السيارة)"],
            "en": [
                "traffic fines?",
                "unpaid fines?",
                "violations?",
                "fine of",
                "pay (the|your) fine",
                "fines",
                "penalty",
                "black points",
                "impound",
            ],
            "arz": ["mokhalafa", "mukhalafa", "mokhalafat", "mukhalafat", "gharama", "ghrama"],
        }
    ],
}

RULE_NAMES = tuple(RULES)
