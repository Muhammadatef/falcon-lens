"""Instruction-like phrase patterns (EN / AR / Arabizi), matched on ``normalise()``d text.

Normalised text is lowercase, has no zero-width or bidi characters, folds Latin homoglyphs, and
folds Arabic letter variants (أ إ آ -> ا, ة -> ه, ي -> ي) with diacritics and tatweel removed, so the
Arabic patterns below are written in the folded form.

``strong`` patterns address an AI or a checker, or forge our own markers, and fire on their own.
``weak`` patterns are common in ordinary text and only count together with another finding or in
a hidden channel. Patterns never capture more than a bounded window (``.{0,N}``), so matching is
linear in the text length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Strength = Literal["strong", "weak"]
Lang = Literal["en", "ar", "arabizi", "any"]


@dataclass(frozen=True, slots=True)
class Pattern:
    id: str
    lang: Lang
    strength: Strength
    regex: re.Pattern[str]


def _p(pid: str, lang: Lang, strength: Strength, rx: str) -> Pattern:
    return Pattern(pid, lang, strength, re.compile(rx))


_AR_ITEM = r"(?:الموقع|الرابط|الرساله|الصفحه|البريد|المحتوي|هذا|هذه)"
_AR_SAFE = r"(?:امن|امنه|امنا|موثوق|موثوقه|سليم|سليمه|شرعي|غير ضار|ليس احتيال|بدون خطر)"
_EN_SAFE = (
    r"(?:safe|legit(?:imate)?|trusted|trustworthy|benign|harmless|clean|verified|genuine|authentic|"
    r"approved|authori[sz]ed|official|whitelisted|allowlisted|pre-approved|cleared|"
    r"not (?:a )?(?:phishing|scam|fraud|malicious)|no warning signs|low risk)"
)
_EN_ITEM = r"(?:site|page|link|url|message|sms|email|e-mail|content|domain|website|text)"
_AI = (
    r"(?:ai|a\.i\.|llm|language model|assistant|chatbot|gpt|claude|scanner|checker|classifier|"
    r"moderator|filter|security (?:bot|scanner|tool|system)|automated (?:system|review|scanner|checker)|"
    r"falcon lens|model)"
)

# "disregard any previous instructions you received about your card" is ordinary customer-service
# wording: the same phrase followed by a recipient/subject qualifier is weak (counts only with
# another finding), not strong.
_EN_BENIGN_TAIL = (
    r"\s+(?:you|we|they)\s+(?:received|got|were sent|have received|sent|gave|issued|had)\b|"
    r"\s+(?:sent|given|provided|issued|emailed|texted)\s+(?:to|by)\s+(?:you|us|the bank)\b|"
    r"\s+(?:about|regarding|concerning|related to|relating to|for)\s+(?:your|the|this|my)\s+"
    r"(?:card|account|pin|password|payment|order|statement|transaction|delivery|parcel|loan|bill|booking)\b"
)
_AR_BENIGN_TAIL = r"\s*(?:المرسله|المستلمه|الواصله|التي (?:ارسلناها|وصلتك|ارسلت)|المتعلقه ب|بخصوص|الخاصه ب)"

_SCHEMA_KEYS = (
    r"claimed_brand_id|instruction_like|script_category|requested_data|risk_score|verdict|"
    r"calibrated_probability|why_evidence_ids|evidence_ids|hard_rule|polarity|generated_by|tool|args"
)
_AW = r"(?<!\w)"  # Arabic-aware word start (\w covers Arabic letters)
_AE = r"(?!\w)"

_EN_IGNORE = (
    r"\b(?:ignore|disregard|forget|override|bypass|skip|drop)\b.{0,40}?\b(?:previous|prior|above|earlier|"
    r"preceding|all|any|your|the|existing|system|original)\b.{0,30}?\b(?:instructions?|prompts?|rules|"
    r"directions|guidelines|directives?|policies|constraints)\b"
)
_AR_IGNORE = (
    _AW + r"(?:تجاهل|تجاهلي|تجاهلوا|اتجاهل|انس|انسي|انسي|اهمل|اهملي|تخط|تخطي|الغ|الغي)" + _AE + r".{0,25}?"
    r"(?:التعليمات|الاوامر|التوجيهات|القواعد|الارشادات|ما سبق|كل ما قيل)"
)

PATTERNS: tuple[Pattern, ...] = (
    # ---------------------------------------------------------------- English
    _p(
        "en.ignore_previous",
        "en",
        "strong",
        _EN_IGNORE + r"(?!" + _EN_BENIGN_TAIL + r")",
    ),
    _p("en.ignore_previous_benign_ctx", "en", "weak", _EN_IGNORE + r"(?=" + _EN_BENIGN_TAIL + r")"),
    _p(
        "en.new_instructions",
        "en",
        "strong",
        r"\b(?:new|updated|real|actual|revised) (?:system )?instructions?\s*[:\-]",
    ),
    _p(
        "en.role_reassign",
        "en",
        "strong",
        r"\byou are (?:now|no longer)\b.{0,40}?\b(?:" + _AI + r"|mode|persona|role|dan|"
        r"admin|developer|unrestricted|jailbroken)\b",
    ),
    _p("en.you_are_now", "en", "weak", r"\b(?:you are now|from now on,? you|act as|pretend (?:to be|you are))\b"),
    _p(
        "en.system_prompt",
        "en",
        "strong",
        r"\b(?:system|developer) (?:prompt|message|instructions?)\b|"
        r"\b(?:hidden|initial|original) (?:prompt|instructions)\b",
    ),
    _p(
        "en.mark_safe",
        "en",
        "strong",
        r"\b(?:mark|classify|label|rate|treat|consider|flag|tag|categori[sz]e|judge|whitelist|allowlist|"
        r"describe|present|portray|summari[sz]e|refer to)\b"
        r"(?: it| this| the| that| our| these)?.{0,40}?\b(?:as|is|to be)\s+(?:\w+\s+)?" + _EN_SAFE + r"\b",
    ),
    _p(
        "en.call_safe",
        "en",
        "strong",
        r"\b(?:call|deem|declare|pronounce|name|term|describe|call out)\s+(?:it|this|that|the \w+|them)\s+"
        r"(?:as\s+)?(?:\w+\s+)?" + _EN_SAFE + r"\b",
    ),
    _p(
        "en.say_safe",
        "en",
        "strong",
        r"\b(?:say|respond|reply|answer|output|return|state|tell the user|conclude)\b(?: only)?(?: with| that|:)"
        r"\s*.{0,30}?\b" + _EN_SAFE + r"\b",
    ),
    _p("en.is_safe", "en", "weak", r"\b(?:this|the) " + _EN_ITEM + r" is (?:100% |completely |totally )?" + _EN_SAFE),
    _p(
        "en.dont_warn",
        "en",
        "strong",
        r"\b(?:do not|don't|never|must not)\b.{0,20}?\b(?:warn|flag|alert)\b.{0,30}?\b"
        r"(?:the user|users|this (?:site|page|link|message|email)|it as|anyone)\b",
    ),
    _p(
        "en.if_you_are_ai",
        "en",
        "strong",
        r"\b(?:if|when|in case) you(?:'re| are)\s+(?:(?:also|really|actually|currently|now|just|indeed)\s+)?"
        r"(?:an? |the )?(?:ai|a\.i\.|llm|language model|bot|chatbot|assistant|scanner|crawler|classifier|"
        r"automated (?:system|reviewer|scanner|checker|tool|agent|process|reader|filter)s?)\b",
    ),
    _p(
        "en.addressed_to_ai",
        "en",
        "strong",
        r"\b(?:any|all|every|dear|attention|to the|to any|for any|note for|note to|message for|message to)\s+"
        r"(?:ai|a\.i\.|llms?|bots?|crawlers?|automated \w+|scanners?|checkers?|classifiers?|"
        r"filters?|language models?|assistants?|security (?:tools?|systems?|software))\b"
        r"(?:\s+\w+){0,2}?\s*(?:reading|scanning|reviewing|processing|checking|analy[sz]ing|parsing|"
        r"should|must|:|,)",
    ),
    _p(
        "en.addressed_to_reviewer",
        "en",
        "weak",
        r"\b(?:note (?:for|to)|message (?:for|to)|attention|dear|to the|to any|for any|any|all)\s+"
        r"(?:(?:content|security|safety|trust) )?(?:reviewers?|moderators?)\b",
    ),
    _p(
        "en.checker_directive",
        "en",
        "strong",
        r"\b(?:ai|bots?|llms?|crawlers?|scanners?|checkers?|classifiers?|"
        r"(?:content |security |safety |trust )?(?:moderators?|reviewers?)|automated (?:systems?|reviewers?|tools?)|"
        r"language models?|security (?:tools?|systems?|software))\s+(?:can|may|could|should|need to|must|will|"
        r"don'?t need to|do not need to|are (?:asked|requested|advised|instructed) to)\s+"
        r"(?:skip|ignore|pass|approve|allow|whitelist|trust|accept|clear|exempt|stop|not|safely)\b",
    ),
    _p(
        "en.vocative_ai",
        "en",
        "strong",
        r"(?:^|[.!?;\n]\s*|\(\s*)(?:automated (?:systems?|tools?|reviewers?|readers?|filters?|scanners?|checkers?)|"
        r"ai(?: models?| systems?| assistants?)?|llms?|bots?|crawlers?|scanners?|checkers?|classifiers?|"
        r"(?:content |security )?(?:moderators?|reviewers?)|language models?|responders?|summari[sz]ers?|"
        r"investigators?|extractors?|agents?|explainers?|auditors?|analysts?)\s*[:,]",
    ),
    _p(
        "en.no_need_warn",
        "en",
        "strong",
        r"\bno (?:need|reason) to (?:warn|flag|alert|report|block|caution|worry the)\b|"
        r"\b(?:need not|needn't|shouldn't|should not|must not|does not need to|doesn't need to) be "
        r"(?:flagged|reported|blocked|warned|marked|treated as (?:suspicious|phishing|a scam))\b",
    ),
    _p(
        "en.ai_address",
        "en",
        "weak",
        r"\b(?:dear|attention|note to|hey|hello|instructions? for)\b.{0,15}?\b" + _AI + r"\b",
    ),
    _p("en.to_ai", "en", "weak", r"\b(?:if you are|as an?|to any|to the)\b.{0,10}?\b" + _AI + r"\b"),
    _p(
        "en.score_steer",
        "en",
        "strong",
        r"\b(?:risk[_ ]?score|verdict|calibrated[_ ]probability|p_clf|risk level)\b\s*(?:[:=]|to|is|"
        r"should be|must be|=>)\s*[\"']?(?:0\b|0\.0|low|none|no_warning_signs|safe|benign|minimal)",
    ),
    _p(
        "en.set_score",
        "en",
        "strong",
        r"\b(?:set|lower|change|override|force|zero|reduce|downgrade)\b.{0,20}?\b(?:risk[_ ]score|verdict)\b|"
        r"\b(?:set|lower|change|override|force|zero|reduce|downgrade)\b.{0,20}?\b(?:this|its|the "
        r"(?:site|page|link|message|email|url|domain|sender)(?:'s)?)\s+(?:risk\s+)?(?:score|level|rating)\b",
    ),
    _p(
        "en.set_score_loose",
        "en",
        "weak",
        r"\b(?:set|lower|change|override|force|zero)\b.{0,20}?\b(?:score|risk level)\b",
    ),
    _p(
        "en.suppress_alerts",
        "en",
        "strong",
        r"\b(?:downgrade|suppress|dismiss|silence|disable|clear|remove|hide|mute|ignore)\b.{0,20}?"
        r"\b(?:alerts?|warnings?|flags?|detections?|alarms?)\b",
    ),
    _p(
        "en.say_looks_fine",
        "en",
        "strong",
        r"\b(?:say|state|report|conclude|answer|respond|reply|tell|write|confirm|keep)\b.{0,40}?\b"
        r"(?:looks? (?:fine|good|ok|okay|normal|clean|legit|safe)|is (?:fine|ok|okay|normal|clean)|"
        r"all (?:good|clear|fine)|nothing (?:is )?(?:wrong|suspicious|malicious|unusual)|no (?:issues?|problems?))\b",
    ),
    _p(
        "en.nothing_wrong",
        "en",
        "weak",
        r"\b(?:nothing (?:is )?(?:wrong|suspicious|malicious|to (?:worry|report|flag))|"
        r"no (?:risks?|danger|threats?))\b",
    ),
    _p(
        "en.approval_claim",
        "en",
        "weak",
        r"\b(?:pre-?approved|pre-?cleared|(?:has|have|been|was|were|is|are) (?:been )?(?:cleared|whitelisted|"
        r"allow-?listed|vetted|audited))\b\s*(?:by|for|as|with)?",
    ),
    _p(
        "en.regulator_claim",
        "en",
        "weak",
        r"\b(?:approved|certified|licen[sc]ed|authori[sz]ed|endorsed|verified|accredited|regulated|cleared|"
        r"vouched|guaranteed)\s+by\s+(?:the\s+)?(?:central bank|regulator|regulators|security team|bank itself|"
        r"bank|ministry|government|police|authorities|cbuae|sama|cbe)\b",
    ),
    _p(
        "en.tool_badge",
        "en",
        "strong",
        r"\b(?:verified|certified|approved|endorsed|validated|checked|scanned|cleared|trusted|vouched|"
        r"authenticated|guaranteed)\b.{0,20}?\b(?:by|with)\s+(?:the\s+)?falcon[ -]?lens\b|"
        r"\bfalcon[ -]?lens\s+(?:verified|certified|approved|trusted|seal|badge|safe|checked|cleared)\b",
    ),
    _p(
        "en.reveal",
        "en",
        "strong",
        r"\b(?:reveal|print|repeat|show|output|leak|tell me|write out|echo|display|disclose)\b.{0,30}?"
        r"(?:system prompt|hidden prompt|initial prompt|instructions above|previous instructions|your instructions|"
        r"your prompt|integrity marker|canary|marker|(?:text|everything|words|content) above)",
    ),
    _p("en.canary", "any", "strong", r"\b(?:canary|integrity marker|confidential marker)\b|\bflc-[0-9a-f]{6,}\b"),
    _p(
        "en.tool_steer",
        "en",
        "strong",
        r"\b(?:render_page|rdap_lookup|cert_lookup|check_reputation|expand_redirects|compare_brand|"
        r"search_similar_scripts|draft_takedown|draft_police_report|block_indicator|raise_alert|upsert_incident|"
        r"requeue_check|export_stix)\b",
    ),
    _p("en.reply_only", "en", "weak", r"\b(?:respond|reply|answer|output|return)\b.{0,15}?\b(?:only|exactly|just)\b"),
    _p("en.jailbreak", "en", "strong", r"\b(?:jailbreak|jailbroken|developer mode|dan mode|do anything now)\b"),
    _p("en.prompt_injection", "en", "weak", r"\bprompt injection\b"),
    # ---------------------------------------------------------------- forged structure (any language)
    _p(
        "any.delimiter_forgery",
        "any",
        "strong",
        r"<<<|\w>>>|\bend_untrusted\b|\buntrusted:[0-9a-f]|<\|(?:im_start|im_end|system|user|assistant|"
        r"endoftext|eot_id|start_header_id)\|>|\[/?(?:inst|sys|system)\]|</?(?:system|instructions?|assistant|"
        r"developer|tool_call|function_call)>|(?:^|\s)#{2,}\s*(?:system|instructions?|new instructions)\b|"
        r"\bbegin (?:system|trusted|developer)\b|\bend of (?:untrusted|data|user) (?:content|input|block|data)\b",
    ),
    _p("any.fake_evidence_id", "any", "strong", r"\bev_[0-9a-f]{8,32}\b"),
    _p("any.evidence_id_like", "any", "weak", r"\bev_[a-z0-9]{8,32}\b"),
    _p(
        "any.schema_field",
        "any",
        "strong",
        r"\b(?:claimed_brand_id|instruction_like|script_category|requested_data|why_evidence_ids|risk_score|"
        r"no_warning_signs|calibrated_probability)\b",
    ),
    _p("any.role_line", "any", "weak", r"(?:^|[\n>])\s*(?:system|assistant|developer|admin)\s*:"),
    _p("any.block_end_claim", "any", "strong", r"\buntrusted (?:block|content|data|text|section)\b"),
    _p(
        "any.schema_mimic",
        "any",
        "strong",
        r"[\"'](?:" + _SCHEMA_KEYS + r")[\"']\s*:.{0,240}?[\"'](?:" + _SCHEMA_KEYS + r")[\"']\s*:",
    ),
    _p(
        "any.schema_key",
        "any",
        "weak",
        r"[\"'](?:claimed_brand_id|instruction_like|script_category|requested_data|risk_score|verdict|"
        r"calibrated_probability|why_evidence_ids|evidence_ids|hard_rule|polarity|generated_by)[\"']\s*:",
    ),
    # ---------------------------------------------------------------- Arabic (folded)
    _p("ar.ignore_previous", "ar", "strong", _AR_IGNORE + r"(?!" + _AR_BENIGN_TAIL + r")"),
    _p("ar.ignore_previous_benign_ctx", "ar", "weak", _AR_IGNORE + r"(?=" + _AR_BENIGN_TAIL + r")"),
    _p(
        "ar.mark_safe",
        "ar",
        "strong",
        _AW
        + r"(?:اعتبر|اعتبري|اعتبروا|صنف|صنفي|قيم|قيمي|سجل|عامل|عاملي|قل ان|قولي ان|اكتب ان|اجب ب)"
        + _AE
        + r".{0,40}?"
        + _AW
        + r"[وف]?"
        + _AR_SAFE
        + _AE,
    ),
    _p("ar.is_safe", "ar", "weak", _AR_ITEM + r"\s*.{0,15}?(?:امن تماما|امن 100|موثوق تماما|امن وموثوق)"),
    _p(
        "ar.you_are_now",
        "ar",
        "strong",
        _AW + r"(?:انت|انتي|انتم)\s*(?:الان|من الان)\s*.{0,20}?(?:مساعد|نموذج|نظام|ذكاء|بوت|روبوت|مسؤول|مطور|مدير)",
    ),
    _p("ar.you_are_now_weak", "ar", "weak", _AW + r"(?:انت|انتي)\s*الان" + _AE + r"|من الان فصاعدا"),
    _p(
        "ar.system_prompt",
        "ar",
        "strong",
        r"(?:موجه|برومبت)\s*(?:النظام|المطور)|(?:تعليمات|اوامر)\s*(?:النظام|المطور|الخفيه|الاصليه)|العلامه السريه",
    ),
    _p(
        "ar.dont_warn",
        "ar",
        "strong",
        _AW + r"(?:لا|ممنوع|يجب الا)\s*(?:تحذر|تحذري|تنبه|تصنف|تضع علامه)" + _AE + r".{0,30}?"
        r"(?:المستخدم|احتيال|خطر|مشبوه|خطير)",
    ),
    _p(
        "ar.reveal",
        "ar",
        "strong",
        _AW + r"(?:اكشف|اظهر|اطبع|كرر|اعرض|انسخ)" + _AE + r".{0,25}?(?:التعليمات|موجه النظام|العلامه|النص السابق)",
    ),
    _p(
        "ar.ai_address",
        "ar",
        "weak",
        r"(?:الذكاء الاصطناعي|المساعد الذكي|نظام الفحص|انظمه الفحص|اداه الفحص|ادوات الفحص|ادوات التحقق|"
        r"برامج الفحص|المدقق الالي|الفاحص الالي|الفاحص|نموذج اللغه|ايها النموذج|ايها المساعد|الي النظام الالي|"
        r"الانظمه الاليه|البوت|الروبوت)",
    ),
    _p(
        "ar.addressed_to_ai",
        "ar",
        "strong",
        r"(?:الي|ملاحظه لـ?|ملاحظه الي|رساله الي|رساله لـ?|تنبيه الي|يا|ايها|عزيزي)\s*"
        r"(?:الذكاء الاصطناعي|المساعد الذكي|انظمه الفحص|نظام الفحص|ادوات الفحص|ادوات التحقق|اداه الفحص|"
        r"برامج الفحص|المدقق|الفاحص|النموذج|البوت|الروبوت|الانظمه الاليه|المراجع الالي)",
    ),
    _p(
        "ar.no_classify",
        "ar",
        "strong",
        r"(?:الرجاء|رجاء|يرجي|نرجو|ارجو)?\s*عدم\s*(?:تصنيف|التصنيف|التحذير|تحذير|الابلاغ|التبليغ|حظر|وضع علامه)",
    ),
    _p(
        "ar.no_need_warn",
        "ar",
        "strong",
        r"(?:لا داعي|لا حاجه|لا يلزم|لا يجب|غير ضروري)\s*(?:لل|الي ال|ل)?(?:تحذير|تنبيه|الابلاغ|التبليغ|حظر|"
        r"تصنيف)",
    ),
    _p(
        "ar.gulf_addressee",
        "ar",
        "strong",
        _AW + r"(?:يا ?اللي|ياللي|يالي|يا من|يا الي)\s*(?:تفحص|تقرا|تقرء|تراجع|تدقق|تحلل|تشوف|تصنف|تتحقق|تقيم|تلخص)",
    ),
    _p(
        "ar.gulf_no_issue",
        "ar",
        "weak",
        _AW + r"و?(?:ما|مافي|لا يوجد|لا توجد|ماكو|مافيه|ما في)\s*(?:فيها|فيه|فيهم|في|عليها|عليه)?\s*(?:اي\s*)?"
        r"(?:شي|شيء|خطر|مخاطر|مشكله|احتيال|خطا|مشاكل)" + _AE,
    ),
    _p(
        "ar.from_bank_itself",
        "ar",
        "weak",
        _AW + r"(?:هذي|هذه|هاذي|هاي|هذا|هادي)\s*(?:الرساله|الصفحه|الرابط|الموقع|الايميل)?\s*"
        r"(?:جايه |جاي |صادره |صادر )?من\s*(?:البنك|المصرف|الجهه)\s*(?:نفسه|ذاته|الرسمي|الرسميه)",
    ),
    _p(
        "ar.regulator_claim",
        "ar",
        "weak",
        r"(?:معتمد|معتمده|مرخص|مرخصه|موثق|موثقه|مصادق|مصادقه|مسجل|مسجله|مضمون|مضمونه)\s*(?:رسميا\s*)?"
        r"(?:من|لدي|عند|بواسطه)\s*(?:ال)?(?:بنك المركزي|مصرف المركزي|البنك المركزي|المصرف المركزي|"
        r"الجهات الرقابيه|الجهات الرسميه|فريق الامن|الحكومه)",
    ),
    _p(
        "ar.tool_badge",
        "ar",
        "strong",
        r"(?:موثق|معتمد|مصادق عليه|مفحوص|مضمون|مفحوصه|معتمده|موثقه)\s*(?:رسميا\s*)?(?:من|بواسطه|لدي|عبر)\s*"
        r"(?:ال)?عدسه الصقر|عدسه الصقر\s*(?:تؤكد|تضمن|توثق|تعتمد|مصادق)",
    ),
    _p(
        "ar.suppress_alerts",
        "ar",
        "strong",
        _AW
        + r"(?:خفض|اخفض|قلل|الغ|الغي|اخف|اسكت|عطل|تجاهل)"
        + _AE
        + r".{0,15}?(?:التحذير|التحذيرات|التنبيه|التنبيهات|الانذار)",
    ),
    # ---------------------------------------------------------------- Arabizi (Latin, digits as letters)
    _p(
        "arabizi.ignore_previous",
        "arabizi",
        "strong",
        r"\b(?:t[ae]?ja+h[ae]?l|tjahal|tejahel|insa|ensa|ensaa|ehmel|ihmal|t5a+ta)\w{0,3}\b.{0,25}?"
        r"\b(?:(?:e|a|i)l[ -]?)?(?:ta3li+ma+t|ta3leemat|ta3limat|awa+mer|awamir|qawa3ed|ta3lima)\b",
    ),
    _p(
        "arabizi.mark_safe",
        "arabizi",
        "strong",
        r"\b(?:e3tabir|e3tber|e3tebr|i3tabir|3tabir|e3teber|sanef|sannif|qool enno|gool enno|qol enno)\w{0,3}\b"
        r".{0,40}?\b(?:amen|aamen|a2men|amin|amina|safe|mawthooq|mawthoq|mawthuq|saleem|salim)\b",
    ),
    _p(
        "arabizi.dont_warn",
        "arabizi",
        "strong",
        r"\b(?:la|ma|mat|matt)\s*(?:t7azer|t7azir|t7athir|t7atheer|tballegh|tbalegh|tballigh|tsanef|tsannif|"
        r"tnabeh|tnabbih)\w*\b(?=.{0,25}?\b(?:7ad|a7ad|ay\s*7ad|ahad|anyone|(?:el|al)\s*(?:user|3ame+l|3emil|"
        r"mostakhdem|zaboun|zabon|client|customer)|(?:el|al)(?:3ame+l|3emil|zaboun|client)|hada|had)\b)|"
        r"\bya\s*(?:bot|ai|robot|model|scanner|checker)\b.{0,30}?\b(?:la|ma|mat|matt)\s*t7azer\w*",
    ),
    _p("arabizi.ya_bot", "arabizi", "strong", r"\bya\s*(?:bot|ai|robot|model|scanner|checker|assistant)\b"),
    _p(
        "arabizi.you_are_now",
        "arabizi",
        "weak",
        r"\b(?:enta|inta|anta|enti|inti)\b.{0,6}?\b(?:(?:e|a)l)?[ -]?(?:2an|2aan|alheen|al7in|hal2|elhin)\b",
    ),
)

STRONG = frozenset(p.id for p in PATTERNS if p.strength == "strong")
