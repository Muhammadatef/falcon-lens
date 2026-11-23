# ruff: noqa: E501
"""Feature lexicon for ``message.scam_intent`` (Arabic MSA + Gulf, English, Arabizi).

Same format and same normaliser as ``lexicon.RULES``: regex fragments written with any alef/yaa/taa form, one group per
feature, OR within a group. Features describe what a message ASKS or CLAIMS, in generic roles ("the bank",
"the police", "a courier"); no real organisation is a feature, so no real organisation is allow-listed or blocked.

Two kinds of feature:
* risk features (ask for a secret, remote access, authority claim, payment, penalty, advance fee ...);
* protective features (``warning_never_share``, ``code_delivery``): wording that says the opposite (a notice that a code
  must never be shared, or a message that only delivers a code).

How they combine is NOT written here: ``intent_weights.json`` holds weights fitted on the TRAIN split only
(``python -m evals.message_text.fit``).
"""

from __future__ import annotations

from falcon_core.signals.message.lexicon import Group

# Features that reuse the rule detectors in ``lexicon.RULES`` (strengthened there): see intent.py.
FROM_RULES: tuple[str, ...] = (
    "otp_request",
    "remote_access",
    "authority",
    "urgency",
    "secrecy",
    "prize",
    "job",
    "investment",
    "fine",
)

_BANK = "(بنك|مصرف|bank)"

FEATURES: dict[str, list[Group]] = {
    # card / PIN / identity-document ask: a noun for the data AND a verb that asks for it
    "ask_card_data": [
        {
            "ar": [
                "(ارسل|ارسلي|زودنا|زودني|اعطنا|اعطني|عطنا|اكتب|ادخل|تاكيد|تحديث|تاكد من|ابي|ابغى|نحتاج|احتاج|مطلوب|يرجى|رد|الرد|بعث|ابعث) "
                "[^.!?]{0,40}?(رقم (ال)?بطاق|بيانات (ال)?بطاق|(ال)?رقم (ال)?سري|رمز (ال)?بن|cvv|بن كود|رقم (ال)?هويه|صوره (ال)?هويه|نسخه (من )?(ال)?هويه|نسخه (من )?(ال)?جواز|صوره (ال)?جواز|الهويه الاماراتيه|تاريخ (ال)?انتهاء)"
            ],
            "en": [
                "(send|share|give|provide|confirm|enter|reply with|update|need|verify|submit|forward) "
                "[^.!?]{0,40}?(card (number|details)|\\bpin\\b|\\bcvv\\b|emirates id|id (number|copy)|passport|expiry|iban|bank details|account details|date of birth)"
            ],
            "arz": [
                "(ersel|ersal|rsel|3tini|e3tini|a3tini|3atini|ab3at|zawedna|7ot|ktb|katab|a7tag|na7tag|abgha|abi) "
                "[^.!?]{0,40}?(raqam (el |al )?(bitaqa|bitaka|card)|bayanat (el |al )?bitaqa|(el |al )?pin\\b|\\bcvv\\b|raqam (el |al )?(huwiya|hawiya)|suret (el |al )?(huwiya|hawiya)|jawaz)"
            ],
        }
    ],
    # a bank/department "security / fraud / support team" claim (a bare "bank" is not a claim)
    "claim_bank_staff": [
        {
            "ar": [
                "(امن|قسم|ادار[هة]|فريق|موظف|دعم|خدم[هة]) (ال)?(عملاء|احتيال|امن|مكافح[هة]|اف|فني|دعم|حمايه|مصرف|بنك|ماليه)",
                "(فريق|قسم) (امن|حمايه|دعم)",
                "(معك|معاك|معكم|انا|نحن) [^.!?,]{0,25}?(من|في) [^.!?,]{0,15}?(بنك|مصرف)",
                "(الدعم الفني|الامن|قسم الاحتيال|مكافحه الاحتيال) (ل|في|ب)?(ال)?(بنك|مصرف)",
                "(بنك|مصرف)[^.!?,]{0,20}?(الامن|الدعم الفني|مكافحه الاحتيال)",
                "(الدعم الفني|الامن|قسم الاحتيال|الاحتيال) (ل|في)?(ال)?(بنك|مصرف)",
            ],
            "en": [
                "(your )?bank('?s)? (security|fraud|support|team|department|staff|officer)",
                "(security|fraud|support|customer service) (team|department|desk|officer)( of| at| from)? (your |the |our )?bank",
                "(this is|i am|i'?m|we are|speaking|calling|contacting)[^.!?]{0,40}?\\b(bank|banking)\\b",
                "this is your bank",
                "fraud department",
                "card (department|services)",
            ],
            "arz": [
                "(ma3ak|ana|ahna|7na|men|min|mn) (el |al |bel |bil )?(bank|masraf)",
                "(dae?m|qism|amn|fariq|mawzaf) (el |al )?(bank|ahtiyal|fraud|security|masraf)",
            ],
        }
    ],
    # utility / telecom / courier / visa-residency role claims
    "claim_service_role": [
        {
            "ar": [
                "شركه (ال)?(كهرباء|ماء|اتصالات|توصيل|شحن|بريد|غاز|انترنت)",
                "(ادار[هة]|دائر[هة]|قسم) (ال)?(اقامه|هجره|جمارك|مرور|تاشيرات|هويه)",
                "(الاقامه|الجمارك|المرور|الهجره)",
                "(مندوب|موظف) (التوصيل|الشحن|الجمارك|الشركه)",
            ],
            "en": [
                "(the )?(electricity|water|gas|internet|telecom|courier|delivery|shipping|postal|customs) (company|provider|department|service|agent|office|depot)",
                "(residency|immigration|visa|customs|traffic|municipality) (department|office|authority|service)",
                "(courier|delivery) (agent|company)",
                "depot",
            ],
            "arz": [
                "sharikat (el |al )?(kahraba|ittisalat|tawseel|shahn|ma)",
                "(idarat|qism|dairat) (el |al )?(iqama|jamarik|muroor|hijra|tashira)",
                "mandoob (el |al )?(tawseel|shahn|jamarik)",
                "(el |al )?(iqama|jamarik)",
            ],
        }
    ],
    # asks the reader to pay / send / transfer money
    "pay_ask": [
        {
            "ar": [
                "(ادفع|ادفعي|سدد|سددي|حول|حولي|حوّل|قم بدفع|قم بتحويل|ارسل (لنا |لي )?(مبلغ|المبلغ|مال|فلوس|\\d)|تحويل (مبلغ|المبلغ|ضمان|رسوم)|دفع (رسوم|مبلغ|المبلغ|ضمان|كفاله)|سداد (رسوم|المبلغ|مبلغ)|ايداع|اشتر)",
                "(يجب|لازم|عليك|يرجى|مطلوب) [^.!?]{0,20}?(دفع|سداد|تحويل)",
            ],
            "en": [
                "\\b(pay|send|transfer|wire|deposit|remit|settle|buy)\\b [^.!?]{0,40}?(aed|dirhams?|usd|usdt|fee|fees|amount|money|funds|cash|gift ?cards?|bail|deposit|fine|\\d)",
                "\\b(pay|send|transfer|wire|deposit)\\b (now|today|immediately|within|the|your|a|an)\\b",
                "(payment|fee|amount) (is )?(due|required|pending|needed)",
            ],
            "arz": [
                "(idfa3|idfa'?a|sadid|7awel|7awwel|ta7weel|ab3at|ersel|ersal|ishtri|eshtri|7ot) [^.!?]{0,40}?(dirham|dirhem|aed|mablagh|flus|fulus|rusoom|rasm|kafala|bitaqat|gift|\\d)",
                "(idfa3|7awel|7awwel|sadid) (halhin|el yom|fawran|alan|elan)",
            ],
        }
    ],
    # a fee / charge / bail attached to a release, registration, processing or customs step
    "fee_word": [
        {
            "ar": [
                "رسوم",
                "كفاله",
                "ضمان",
                "عموله",
                "جمارك",
                "تسجيل (ال)?(رسوم)",
                "مصاريف",
                "مبلغ (ضمان|تامين)",
            ],
            "en": [
                "(processing|registration|release|transfer|customs|admin|handling|delivery|redelivery|visa|clearance) fees?",
                "\\bfees?\\b",
                "\\bbail\\b",
                "\\bcustoms\\b",
                "deposit",
                "guarantee (amount|fee|payment)",
            ],
            "arz": ["rusoom", "rasm\\b", "kafala", "jamarik", "3amola", "amola", "masarif", "damaan"],
        }
    ],
    "gift_card_crypto": [
        {
            "ar": [
                "بطاق(ات|ه) (ال)?(هدايا|هديه|شحن|ايتيونز|قوقل|جوجل|ابل)",
                "كروت (ال)?(شحن|هدايا)",
                "usdt",
                "(عمل(ات|ه) رقمي[هة]|محفظ[هة] (ال)?(رقمي[هة]|الكترونيه)|بيتكوين|كريبتو|عمله مشفره)",
            ],
            "en": [
                "gift ?cards?",
                "itunes",
                "\\busdt\\b",
                "crypto(currency)?",
                "bitcoin",
                "wallet address",
                "digital wallet",
                "voucher codes?",
            ],
            "arz": [
                "gift ?cards?",
                "bitaqat (el |al )?(hadaya|hedaya|shahn)",
                "usdt",
                "kripto",
                "crypto",
                "bitcoin",
                "mo7faza raqmiya",
                "ma7faza raqmiya",
            ],
        }
    ],
    # money to a PERSON: personal account, friend's account, new-number stories
    "personal_account": [
        {
            "ar": [
                "حساب (شخصي|صديقي|صاحبي|قريبي|اخي|ابن عمي|خاص)",
                "(رقمي|رقم) (ال)?جديد",
                "(تلفوني|جوالي|هاتفي|موبايلي) (انكسر|ضاع|تعطل|انسرق|تلف|مكسور)",
                "(ضاع|ضيعت|فقدت|انكسر|تعطل) (تلفوني|جوالي|هاتفي|موبايلي)",
                "(انا|معك) (ابنك|بنتك|اخوك|قريبك|ابوك|امك|اخوك|صديقك)",
                "قريبك",
                "ظرف طارئ|امر طارئ|طارئ جدا",
                "حساب (مصرفي )?(باسم|اخر)",
            ],
            "en": [
                "(personal|friend'?s|relative'?s|colleague'?s|another|different|third[- ]party|private) (bank )?account",
                "(my )?new (number|phone|line)",
                "(lost|broke|broken|damaged) (my )?phone",
                "(it'?s|this is|its) (me|your (son|daughter|brother|sister|dad|mum|mom|friend|cousin))",
                "(urgent|emergency)[^.!?]{0,40}?(send|transfer|need)",
                "i (cannot|can'?t) (talk|call|speak)",
            ],
            "arz": [
                "7esab (shakhsi|sa7bi|sahbi|sadiqi|qaribi|akhi)",
                "(el )?rakam (el )?(jdid|jadid)",
                "(telefoni|jawwali|mobaili|hatfi)[^.!?]{0,15}?(inkasar|da3|dae3|ta3tal)",
                "ana (ibnek|ibnak|bintek|akhuk|akhoek|sa7bak|sadiqak|qaribak)",
                "amr ta?r?e?2?i?",
            ],
        }
    ],
    # a penalty / consequence for not complying
    "penalty": [
        {
            "ar": [
                "(سيتم|بيتم|راح يتم|بنقطع|بتنقطع|بتوقف|بنوقف|ستلغى|ستلغي|ستوقف) [^.!?]{0,25}?(ايقاف|حظر|تعليق|الغاء|تجميد|حجز|قطع|ترحيل|القبض|توقيف|ايقافه|ايقافها)",
                "(ايقاف|حظر|تجميد|تعليق|قطع|الغاء|حجز) (حسابك|بطاقتك|خطك|رقمك|الخدمه|الاقامه|مركبتك|سيارتك|الكهرباء)",
                "(حظر|تجميد|ايقاف|قطع|الغاء|حجز) (ال)?(حساب|بطاقه|خط|رقم|خدمه|اقامه|مركبه|سياره)",
                "اجراءات قانونيه",
                "(الترحيل|القبض عليك|السجن|المحاكمه|الحبس)",
                "(ستتحمل|تتحمل|تتحملون) (ال)?(غرامه|مسووليه)",
                "(انوقف|توقف|اتوقف|تعطل|تجمد) (حسابك|بطاقتك|حسابي)",
                "وإلا",
                "والا (بيتم|تم|سيتم|بتنحجز|بنحجز|بنرسل|بيتم|ستتحمل|تتحمل|بنقطع|بنوقف|بيوقف|بتوقف)",
                "نقاط سوداء",
                "الدوريه",
            ],
            "en": [
                "will be (suspended|blocked|closed|frozen|cancell?ed|deactivated|cut|impounded|deported|terminated|disconnected|arrested|locked)",
                "(suspend|block|freeze|close|cancel|deactivate|impound|disconnect)(ed|d|s)? (your )?(account|card|line|number|service|visa|residency|vehicle|power)",
                "legal action",
                "(arrest|deport|prosecut|jail|imprison)",
                "black points",
                "\\bor (else|your)",
                "(avoid|to avoid) [^.!?]{0,30}?(fine|penalty|arrest|deportation|impound|block|suspension|closure|cut)",
                "(power|electricity|service) (will )?be cut",
                "have been (blocked|suspended|deactivated)",
            ],
            "arz": [
                "(bytm|byetm|ra7|rah|7ayetm|byt2ata3|bnwaqef|bnqta3) [^.!?]{0,25}?(hazr|ta3leeq|ilgha|tajmeed|7ajz|qata3|tarheel|qabd|iqaf|iwqaf|waqf)",
                "(hazr|tajmeed|iqaf|waqf|qata3|7ajz|ilgha) (hesabak|bitaqtak|khattak|raqmak|el khidma|el iqama)",
                "(w3alek|wala|ow ala|3alek|wa 3alek) (gharama|ghrama|qanun|qadiya)",
                "iza ma [^.!?]{0,30}?(hazr|tajmeed|iqaf|ta3leeq|qata3|7ajz)",
                "tarheel",
                "7esabak (twaqqaf|inwaqaf|mowaqaf|ta3al)",
            ],
        }
    ],
    # account-trouble claim ("suspicious activity", "problem with your account")
    "account_trouble": [
        {
            "ar": [
                "(حركه|عمليه|عمليات|سحب|دخول|نشاط|محاوله) (غريب[هة]?|مشبوه[هة]?|غير (طبيعي|عادي|مصرح|معروف)|مب طبيعي|غلط|غير مسموح)",
                "(مشكل[هة]|خلل|عطل|فايروس|فيروس|اختراق|مخاطر) (في|بال|ب|يهدد|على)?",
                "(حسابك|بطاقتك|خطك|رقمك) (موقوف|معلق|محظور|مجمد|انوقف|توقف|تعطل|مهدد|مخترق|ملغي|ملغى)",
                "(تم|تحديث|يلزم) تحديث (بياناتك|معلوماتك|حسابك)",
                "(تحديث|تحقق|توثيق|تفعيل) (بيانات|حساب|هويه)",
                "(تفعيل|توثيق) (حسابك|بطاقتك)",
                "(بلاغ|قضيه|دعوى|شكوى) (باسمك|ضدك|بحقك|مسجل)",
                "بسم(ك|ي)",
            ],
            "en": [
                "(unusual|suspicious|unauthori[sz]ed|strange|fraudulent|illegal) (activity|login|transaction|payment|transfer|access|attempt|withdrawal)",
                "(problem|issue|fault|virus|breach|hack|malware|risk)( with| on| in)? (your )?(account|card|device|phone|bank|line)",
                "(technical )?(fault|problem|issue)",
                "your (account|card|line|number|visa|residency|service)( has| is| will| was)? (been )?(suspended|blocked|frozen|deactivated|cancell?ed|locked|compromised|overdue|on hold|held|unpaid)",
                "(verify|update|confirm|reactivate|restore|unlock)( your)? (account|details|identity|information|card|data)",
                "(case|warrant|complaint|report) (has been|was|is)? ?(opened|registered|filed|issued|against)",
                "overdue",
                "unpaid",
                "(held|held at) (the )?(depot|customs|warehouse)",
                "against (your|you)",
            ],
            "arz": [
                "(7araka|haraka|amaliya|3amaliya|dokhool|nashat) (ghalat|ghareeba|mashbooha|ghair|mesh|moshbooha|mashbouha|ghayr)",
                "(moshkila|mushkila|khalal|virus|fayrus|ikhtiraq) (bel|fi|3ala)?",
                "(hesabak|bitaqtak|khattak|raqmak) (twaqqaf|mowaqqaf|ma7zoor|mojammad|ta3al|mo3allaq|inwaqaf)",
                "(qadiya|balagh|dawa) (bismak|3alek|dedak|bi ismak)",
                "(tahdeeth|tawtheeq|ta2keed|tafeel|tafeel) (bayanat|hesab|bitaqa|hawiya|huwiya)",
                "ma3lomat (el )?bank",
            ],
        }
    ],
    # asks to move to another app / private group
    "off_platform": [
        {
            "ar": [
                "(تيليجرام|تلغرام|تليجرام|تلجرام|سيجنال|سيغنال|واتس|واتساب|ويكر|فايبر|فيبر)",
                "(قروب|مجموعه|جروب|مجموعة) (خاصه|خاص|مغلقه|التلغرام|الواتس|الواتساب|تيليجرام|تلغرام)",
                "(تطبيق|برنامج) (اخر|ثاني|مراسله|محادثه|مراسلات)",
                "(تواصل|كلمني|راسلني|ضيف|اضف|انضم) [^.!?]{0,25}?(خاص|قروب|مجموعه|تطبيق|ال?تلغرام|الواتس|الواتساب)",
                "(انضم|انضمي) [^.!?]{0,15}?(قروب|مجموعه|قناه|جروب)",
            ],
            "en": [
                "telegram",
                "whats ?app",
                "signal app",
                "\\bwechat\\b",
                "viber",
                "(private|vip|exclusive|closed|secret) (group|channel|chat)",
                "(another|different|other) (chat )?(app|platform|messenger)",
                "(add|message|contact|text|join|dm)( me| us| our| my)?[^.!?]{0,25}?(on|via|in|at|to)[^.!?]{0,15}?(telegram|whats ?app|signal|group|private)",
                "(continue|chat|talk|speak) (with (us|me) )?(on|via|in)[^.!?]{0,15}?(app|telegram|whats ?app|private)",
            ],
            "arz": [
                "(telegram|tele?gram|whats ?app|watsab|watsap|signal|viber|wechat)",
                "(group|qroub|croub|jroup|gruppe) (khass|private|vip|mghlaq)",
                "(kalemna|kalmoni|rasilna|daf|udkhol|ndam|indam)[^.!?]{0,20}?(telegram|whats ?app|group|qroub|khass|tatbiq)",
                "tatbiq (akhar|thani|tani)",
            ],
        }
    ],
    # callback instruction with a number
    "callback": [
        {
            "ar": [
                "(اتصل|اتصلي|كلم|كلمني|كلمنا|تواصل|اتصلوا|كلمونا|رن|رنو|رنوا|راسل|راسلنا) [^.!?]{0,30}?(على|ب|علي|عالرقم|الرقم|رقم)[^.!?]{0,15}?\\d{6,}",
                "(اتصل|اتصلي|كلم|كلمني|كلمنا|تواصل|رن|رنو|رنوا)[^.!?]{0,25}?(فورا|حالا|الحين|هالحين|الان|مباشره|بسرعه|عاجل)",
                "(للتفعيل|لتفعيل|للتحقق|للتواصل|للاستفسار|للتاكيد|لتجنب) [^.!?]{0,15}?(اتصل|رقم)",
                "\\d{9,}",
                "(الخط (الساخن|العاجل|المباشر))",
                "(اتصل|اتصلي|كلم|كلمني|كلمنا|تواصل)[^.!?]{0,15}?\\d{6,}",
            ],
            "en": [
                "(call|phone|dial|ring|contact|text|whatsapp|reach)( us| me| the officer| our (agent|line|team|number)| back)?[^.!?]{0,30}?\\d{6,}",
                "(call|phone|dial|contact)( us| me| the officer| our (agent|line|team))?( back)?[^.!?]{0,20}?(immediately|now|urgently|today|right away|asap)",
                "(urgent|hot|emergency) (line|number|hotline)",
                "call (the )?(officer|agent|manager|number)",
                "\\d{9,}",
            ],
            "arz": [
                "(etasel|ittasel|etsel|ittasil|kalemna|kalemni|kalmoni|rn|rin|ittisal)[^.!?]{0,25}?\\d{6,}",
                "(etasel|ittasel|etsel|ittasil|kalemna|kalemni|kalmoni)[^.!?]{0,25}?(fawran|halhin|alan|elan|3ajil|bsora3a)",
                "\\d{9,}",
            ],
        }
    ],
    # prize / lottery / visa / job offers (advance-fee family): re-uses prize and job and adds visa + guaranteed
    "offer_visa_guaranteed": [
        {
            "ar": [
                "تاشير[هة] (عمل|دخول|زياره|اقامه|مضمونه)",
                "(فيزا|تاشيره|اقامه) (مضمونه|جاهزه|مضمون)",
                "(مضمون|مضمونه|مضمونة|مضمونا)",
                "(ارباح|ربح|عوائد|راتب|دخل) (يومي|يوميا|شهري)",
                "(ضاعف|تضاعف) (اموالك|مالك|فلوسك)",
                "(بدون|بلا) (خبره|مجهود|شهاده)",
                "(سحب|قرعه) (على|علي|جوائز|رابح)",
                "(سياره|ايفون|ايفون|ذهب|مليون)[^.!?]{0,15}?(فزت|ربحت|الفائز|الجائزه|السحب)",
                "(الفائز|فزت|ربحت|فاز|ربح)[^.!?]{0,25}?(سياره|ايفون|درهم|مليون|جائزه|ذهب|مبلغ)",
            ],
            "en": [
                "visa (is |has been )?(approved|ready|guaranteed|application)",
                "(entry|work|residence|residency|employment) (permit|visa)",
                "guaranteed",
                "(daily|weekly|monthly) (profit|returns?|income|earnings|payout)",
                "(no|without) (experience|skills|qualification|investment risk)",
                "earn [^.!?]{0,12}?(aed|usd|dirhams?)?[^.!?]{0,6}?(per|a|every) (day|week|hour)",
                "(double|triple) your (money|investment)",
                "(you (have )?won|you are (the )?winner|you were selected|selected as)",
                "(lucky )?(draw|raffle)",
                "(lottery|jackpot)",
                "(release|claim|receive) (the |your )?(prize|funds|reward|winnings|parcel|package|refund)",
                "(refund|compensation)",
            ],
            "arz": [
                "(visa|tashira|tashirah|iqama) (madmoona|mudmuna|jahiza|mawafaq)",
                "(madmoon|madmoona|mudmoon)",
                "(arba7|rib7|dakhl|raatib|ratib) (yawmi|shahri|yawmiyan)",
                "(daa?3ef|dae?3if) (flusak|amwalak)",
                "(rabe7t|rabaht|fezt|fuzt|rbe7t|fezet|mabrouk|mabrook|mabrok) ",
                "(sa7b|qur3a|qura3)",
                "(jaeza|ja2eza|jayza|jaa2iza)",
            ],
        }
    ],
    # protective: the message tells you NOT to share / that the sender will never ask
    "warning_never_share": [
        {
            "ar": [
                "لا (تشارك|تشاركه|تشاركها|تعطي|تعطيه|تعطيها|تعط|تفصح|تفشي|تفشيه|تفشيها|تقدم|تقدمه|تزود|تذكر|تعطها|تعطه)",
                "لا تشاركه",
                "(لن|ما|مو|مب) (نطلب|يطلب|تطلب|يطلبون|نسالك|يسالك|نسالك|نطلبه|يطلبه|يطلبها|تطلبه|يتصل)",
                "(لن|ما) (يطلب|يطلبون|نطلب|نسال|يسال|يسالون)",
                "تنبيه(ات)? (توعوي|امني)",
                "احذر|احذروا|انتبه|انتبهوا|حذار|توعيه|تحذير",
                "(تجاهل|تجاهلي|تجاهلوا) (هذه|هالرساله|الرساله|الرسالة)",
                "ان لم تكن (انت|أنت)",
                "اذا (لم تطلب|ما طلبت)",
                "(لو|اذا|اذا) (مب|مو|لم تكن) انت",
            ],
            "en": [
                "(do not|don'?t|never|must not|should not|shouldn'?t|please do not|please don'?t) (share|give|tell|disclose|reveal|provide|send|forward|read out)",
                "(will|would|do|does|shall) (never|not) (ask|request|call|message|contact|require|send)",
                "(never|not) (ask|asks|asking) (you )?(for|to)",
                "(staff|bank|police|authorities|we) (will )?never",
                "if (this was not you|you did not (request|make|initiate)|you didn'?t (request|make|initiate)|it wasn'?t you|not you)",
                "(ignore|disregard) (this|the) message",
                "(awareness|beware|stay alert|be careful|stay safe|scam alert|fraud alert|be aware)",
                "(for your (security|safety)|keep (it|this) safe)",
                "(warn(ing|s)?|alert)[^.!?]{0,40}?(scam|fraud|phishing|impersonat)",
            ],
            "arz": [
                "(la|ma|mesh|moush|mu) (tsharik|tshare|tshareek|tsherek|ta3ti|ta3tee|ta3tiha|tdhkr|tzawwed|tshariko)",
                "(la|ma) (tshareek|tshare|tsharek|tsharik)",
                "(ma|mesh|moush|la|lan) (byetlob|bytlob|yetlob|tetlob|nitlob|netlob|byeseal|byes2al|nes2al|nas2al|y?tasel|yetasel)",
                "(abadan|abdan|mutlaqan|iblan)",
                "(entabeh|entabih|e7thar|i7thar|ihzar|e7zar|tanbeeh|tawe3ya)",
                "(iza|lw|law) (mesh|moush|mu|mish) (enta|inta|ant)",
                "(tajahal|tjahal|ignore) ",
            ],
        }
    ],
    # protective: the message delivers a one-time code (XXXXXX placeholder, digits, or "is <code>")
    "code_delivery": [
        {
            "ar": [
                "(رمز|كود|رقم) (ال)?(تحقق|تحقق|دخول|تاكيد|مرور)[^.!?]{0,20}?(هو|:|=|\\d{4,}|x{3,})",
                "(رمزك|كودك|رمز التحقق|رمز الدخول)[^.!?]{0,12}?(هو|:|\\d{4,}|x{3,})",
                "x{4,}",
                "(صالح|صالحه|ينتهي|تنتهي)[^.!?]{0,15}?(دقائق|دقيقه|دقايق)",
                "الرمز (هو|:)",
            ],
            "en": [
                "(your |the )?(one[- ]time|verification|login|security|confirmation|authenticat\\w+) (code|password|pin)( is| :|:|=)",
                "(\\d{4,8}|x{3,}) is (your|the) (\\w+ ){0,3}?(code|otp|password|pin)",
                "(code|otp|pin)( is|:)[^.!?]{0,6}?(\\d{4,8}|x{3,})",
                "(expires?|valid)( in| for| within)? \\d+ ?(minutes?|mins?)",
                "x{4,}",
                "(enter|use) (this|the) code (to|in) (log ?in|sign ?in|verify|confirm|complete)",
            ],
            "arz": [
                "(ramz|kod|code) (el )?(ta7aqoq|taaqoq|tahaqoq|ta7aquq|dokhool|verification|tawtheeq)[^.!?]{0,20}?(howa|huwa|:|\\d{4,}|x{3,})",
                "x{4,}",
                "(salih|saleh|yantahi|byentehi) [^.!?]{0,15}?(daqaiq|daqayeq|daqiqa|dakaek)",
            ],
        }
    ],
}

# i18n display of the strongest features reported in ``observed`` (names only, never the text)
FEATURE_NAMES: tuple[str, ...] = (*FROM_RULES, *FEATURES.keys())
