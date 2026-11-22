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

_SCHEMA_KEYS = (
    r"claimed_brand_id|instruction_like|script_category|requested_data|risk_score|verdict|"
    r"calibrated_probability|why_evidence_ids|evidence_ids|hard_rule|polarity|generated_by|tool|args"
)
_AW = r"(?<!\w)"  # Arabic-aware word start (\w covers Arabic letters)
_AE = r"(?!\w)"

PATTERNS: tuple[Pattern, ...] = (
    # ---------------------------------------------------------------- English
    _p(
        "en.ignore_previous",
        "en",
        "strong",
        r"\b(?:ignore|disregard|forget|override|bypass|skip|drop)\b.{0,40}?\b(?:previous|prior|above|earlier|"
        r"preceding|all|any|your|the|existing|system|original)\b.{0,30}?\b(?:instructions?|prompts?|rules|"
        r"directions|guidelines|directives?|policies|constraints)\b",
    ),
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
        r"\b(?:if|when|in case) you(?:'re| are)\b.{0,12}?\b(?:an? )?(?:ai|a\.i\.|llm|language model|bot|"
        r"chatbot|assistant|automated|scanner|crawler|classifier)\b",
    ),
    _p(
        "en.addressed_to_ai",
        "en",
        "strong",
        r"\b(?:any|all|every|dear|attention|to the|to any|for any|note for|note to|message for|message to)\s+"
        r"(?:ai|a\.i\.|llms?|bots?|crawlers?|automated \w+|scanners?|checkers?|reviewers?|classifiers?|"
        r"moderators?|filters?|language models?|assistants?|security (?:tools?|systems?|software))\b"
        r"(?:\s+\w+){0,2}?\s*(?:reading|scanning|reviewing|processing|checking|analy[sz]ing|parsing|"
        r"should|must|:|,)",
    ),
    _p(
        "en.vocative_ai",
        "en",
        "strong",
        r"(?:^|[.!?;\n]\s*|\(\s*)(?:automated (?:systems?|tools?|reviewers?|readers?|filters?|scanners?|checkers?)|"
        r"ai(?: models?| systems?| assistants?)?|llms?|bots?|crawlers?|scanners?|checkers?|classifiers?|"
        r"(?:content |security )?(?:moderators?|reviewers?)|language models?)\s*[:,]",
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
        r"\b(?:set|lower|change|override|force|zero)\b.{0,20}?\b(?:risk[_ ]score|score|verdict|risk level)\b",
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
    _p("any.fake_evidence_id", "any", "strong", r"\bev_[a-z0-9]{8,32}\b"),
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
    _p(
        "ar.ignore_previous",
        "ar",
        "strong",
        _AW + r"(?:تجاهل|تجاهلي|تجاهلوا|اتجاهل|انس|انسي|انسي|اهمل|اهملي|تخط|تخطي|الغ|الغي)" + _AE + r".{0,25}?"
        r"(?:التعليمات|الاوامر|التوجيهات|القواعد|الارشادات|ما سبق|كل ما قيل)",
    ),
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
        r"tnabeh|tnabbih)\w*\b",
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
