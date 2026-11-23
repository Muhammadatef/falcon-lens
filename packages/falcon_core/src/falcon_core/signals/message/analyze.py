# ruff: noqa: E501
"""Message pipeline (deterministic part): rule features, brand mentions, child inputs.

Registered signals: ``message.rules`` (emits message.rule.<x>), ``message.children`` and
``message.brand_mention``. ``analyze_message`` is the entry the worker uses to also get the child inputs
(URLs and phones) that go through the URL pipeline (hard rule H5).
"""

from __future__ import annotations

import base64
import binascii
import re
import urllib.parse
from dataclasses import dataclass, field

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.brands.registry import BrandRegistry, default_registry
from falcon_core.signals.limits import HARD_MAX_MESSAGE_CHARS, InputTooLarge
from falcon_core.signals.message.extract import (
    ChildInput,
    extract_phones,
    extract_urls,
    mask_phone,
)
from falcon_core.signals.message.intent import floor_evidence, scam_intent
from falcon_core.signals.message.normalize import MAX_MESSAGE_CHARS, normalize
from falcon_core.signals.message.rules import RuleHit, find_rules
from falcon_core.signals.message.scripts import script_match_offline
from falcon_core.signals.url.canonical import canonicalize, psl_split
from falcon_core.signals.url.display import display_url
from falcon_core.signals.url.textutil import compact, defang

T1_MS = 100
# Rules and the brand check read the first and last MAX_LINK_SCAN_CHARS // 2 characters in 8 KiB windows (expensive,
# so bounded for CPU). Link extraction is NOT windowed: it reads the whole input (<= HARD_MAX_MESSAGE_CHARS).
MAX_LINK_SCAN_CHARS = 65_536
_INTENT_OVERLAP = 512  # chars shared by neighbouring intent windows so a message is not cut in two
_DATA_URI = re.compile(
    r"(?<![a-z0-9+.-])data:([a-z0-9.+/-]{0,80})((?:;[a-z0-9=.+-]{1,40}){0,4}),([^\s\"'<>]{0,65536})", re.I
)
_ACTIVE = re.compile(r"<\s*(?:form|script|iframe)\b|javascript:", re.I)
_IN = ("message", "email", "image")

SPEC_RULES = SignalSpec(
    name="message.rules",
    family="message",
    tier="T1",
    input_types=_IN,
    timeout_ms=T1_MS,
    network="none",
    emits=tuple(
        f"message.rule.{r}"
        for r in (
            "urgency",
            "secrecy",
            "otp_request",
            "remote_access",
            "payment",
            "authority",
            "prize",
            "job",
            "investment",
            "delivery_fee",
            "fine",
        )
    ),
)
SPEC_CHILDREN = SignalSpec(
    name="message.children",
    family="message",
    tier="T1",
    input_types=_IN,
    timeout_ms=T1_MS,
    network="none",
    emits=(
        "message.contains_url",
        "message.contains_phone",
        "message.limit_exceeded",
        "message.data_uri",
        "message.data_uri_active",
    ),
)
SPEC_INTENT = SignalSpec(
    name="message.scam_intent",
    family="message",
    tier="T1",
    input_types=_IN,
    timeout_ms=T1_MS,
    network="none",
    emits=("message.scam_intent", "message.floor_pair"),
)
SPEC_INTENT = SignalSpec(
    name="message.scam_intent",
    family="message",
    tier="T1",
    input_types=_IN,
    timeout_ms=T1_MS,
    network="none",
    emits=("message.scam_intent",),
)
SPEC_BRAND = SignalSpec(
    name="message.brand_mention",
    family="message",
    tier="T1",
    input_types=_IN,
    timeout_ms=T1_MS,
    network="none",
    emits=("message.brand_mention", "message.brand_url_mismatch"),
)

_DISPLAY = {
    "urgency": ("Pressure to act immediately", "ضغط للتصرف فورا"),
    "secrecy": ("Asks you to keep it secret", "يطلب منك إبقاء الأمر سرا"),
    "otp_request": ("Asks for a verification code or PIN", "يطلب رمز تحقق أو رقما سريا"),
    "remote_access": ("Asks you to install a remote-access app", "يطلب تثبيت تطبيق تحكم عن بعد"),
    "payment": ("Asks for a payment or card details", "يطلب دفعا أو بيانات بطاقة"),
    "authority": (
        "Claims to be police, a ministry or a bank",
        "ينتحل صفة شرطة أو جهة حكومية أو بنك",
    ),
    "prize": ("Prize or reward claim", "ادعاء جائزة أو مكافأة"),
    "job": ("Job offer wording", "صياغة عرض وظيفة"),
    "investment": ("Investment or trading pitch", "عرض استثمار أو تداول"),
    "delivery_fee": ("Delivery fee wording", "رسوم توصيل أو شحن"),
    "fine": ("Fine or violation wording", "مخالفة أو غرامة"),
}


@dataclass
class MessageAnalysis:
    evidence: list[Evidence] = field(default_factory=list)
    children: list[ChildInput] = field(default_factory=list)
    truncated: bool = False


def _rules_over(windows: list[str]) -> list[RuleHit]:
    """Rule hits of the first window, plus rules that only fire in later windows (padding in front cannot hide them)."""
    hits = list(find_rules(windows[0]))
    have = {h.rule for h in hits}
    for w in windows[1:]:
        hits += [h for h in find_rules(w) if h.rule not in have and not have.add(h.rule)]  # type: ignore[func-returns-value]
    return hits


def _data_uri_evidence(text: str) -> list[Evidence]:
    """``data:`` URIs are not links the URL pipeline can fetch: informational (weight 0), and risk only when the
    payload (inline or base64, read up to 64 KiB) carries a form, script, iframe or ``javascript:``."""
    found = 0
    active = False
    mimes: list[str] = []
    for m in _DATA_URI.finditer(text):
        found += 1
        if found > 20:
            break
        mime, params, payload = m.group(1).lower(), m.group(2).lower(), m.group(3)
        if len(mimes) < 5:
            mimes.append(mime or "text/plain")
        try:
            if ";base64" in params:
                raw = base64.b64decode(payload + "=" * (-len(payload) % 4), validate=False)
            else:
                raw = urllib.parse.unquote_to_bytes(payload)
        except (binascii.Error, ValueError):
            raw = b""
        body = raw.decode("utf-8", "replace")
        if _ACTIVE.search(body):
            active = True
    if not found:
        return []
    out = [
        Evidence(
            signal="message.data_uri",
            family="message",
            polarity="neutral",
            observed={"count": min(found, 20), "mimes": mimes},
            display={"en": "Contains an inline data: address", "ar": "يحتوي على عنوان data: مضمّن"},
        )
    ]
    if active:
        out.append(
            Evidence(
                signal="message.data_uri_active",
                family="message",
                observed={"count": min(found, 20), "mimes": mimes},
                display={
                    "en": "An inline data: address carries a form or script",
                    "ar": "عنوان data: مضمّن يحمل نموذجا أو شيفرة",
                },
            )
        )
    return out


def limit_exceeded_evidence(family: str, reason: str, size: int) -> Evidence:
    """Risk evidence: the input was larger than the analysers read. Padding must never lower a verdict
    (docs/SCORING.md §2: ``<family>.limit_exceeded``)."""
    return Evidence(
        signal=f"{family}.limit_exceeded",
        family=family,
        observed={"reason": reason, "size": size},
        display={
            "en": "Unusually large or deeply nested input; only part of it could be read",
            "ar": "محتوى كبير أو متداخل بشكل غير معتاد؛ لم نتمكن من قراءته كاملا",
        },
    )


def _rule_evidence(hits: list[RuleHit], brand_named: bool = False) -> list[Evidence]:
    names = {h.rule for h in hits}
    # H6 identity half: an explicit authority/bank claim, or a registered brand named in the message.
    h6 = "authority" in names or brand_named
    out = []
    for h in hits:
        en, ar = _DISPLAY[h.rule]
        out.append(
            Evidence(
                signal=f"message.rule.{h.rule}",
                family="message",
                observed={
                    "rule": h.rule,
                    "langs": list(h.langs),
                    "spans": [list(s) for s in h.spans],
                    "count": h.count,
                },
                display={"en": en, "ar": ar},
                # H6: OTP / remote-access ask together with authority or bank impersonation
                hard_rule="H6" if h6 and h.rule in ("otp_request", "remote_access") else None,
            )
        )
    return out


def _brand_evidence(text: str, urls: list[ChildInput], reg: BrandRegistry) -> list[Evidence]:
    nm = normalize(text, collapse=False).text
    comp = compact(text)
    found = []
    for b in reg.brands:
        hit = any(
            (re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", nm) if len(t) < 6 else t in comp)
            for t in b.tokens_en
            if len(t) >= 4
        ) or any(t in comp for t in b.tokens_ar)
        if hit:
            found.append(b)
    if not found:
        return []
    out = [
        Evidence(
            signal="message.brand_mention",
            family="message",
            polarity="neutral",
            observed={"brands": [b.brand_id for b in found], "demo": any(b.is_demo for b in found)},
            display={"en": "Mentions a known brand", "ar": "يذكر جهة معروفة"},
        )
    ]
    bad = []
    for u in urls:
        c = canonicalize(u.value)
        if not c.ok:
            continue
        _s, dom, suf, _p = psl_split(c.host)
        reg_dom = f"{dom}.{suf}".lower()
        if not reg.is_official(reg_dom):
            bad.append(defang(reg_dom))
    if bad:
        out.append(
            Evidence(
                signal="message.brand_url_mismatch",
                family="message",
                observed={
                    "brands": [b.brand_id for b in found],
                    "unofficial_domains": sorted(set(bad))[:5],
                },
                display={
                    "en": "Names a brand but links to a different domain",
                    "ar": "يذكر جهة لكن الرابط على نطاق مختلف",
                },
            )
        )
    return out


def analyze_message(text: str, reg: BrandRegistry | None = None) -> MessageAnalysis:
    if len(text) > HARD_MAX_MESSAGE_CHARS:
        raise InputTooLarge(f"message longer than {HARD_MAX_MESSAGE_CHARS} characters")
    full = text
    truncated = len(text) > MAX_MESSAGE_CHARS
    reg = reg or default_registry()
    res = MessageAnalysis(truncated=truncated)
    wide = text
    if truncated:
        # Fail closed: rules and brand check read the head and tail windows; links come from the WHOLE text.
        if len(text) > MAX_LINK_SCAN_CHARS:
            wide = text[: MAX_LINK_SCAN_CHARS // 2] + "\n" + text[-MAX_LINK_SCAN_CHARS // 2 :]
        res.evidence.append(limit_exceeded_evidence("message", "too_long", len(text)))
    windows = [wide[i : i + MAX_MESSAGE_CHARS] for i in range(0, len(wide), MAX_MESSAGE_CHARS)] or [""]
    text = windows[0]
    urls = extract_urls(full)
    phones = extract_phones(full)
    res.evidence += _data_uri_evidence(full)
    brand_ev: list[Evidence] = []
    seen_brand: set[str] = set()
    for w in windows:  # a brand claim pushed past the first window by padding is still seen
        for e_ in _brand_evidence(w, urls, reg):
            if e_.signal not in seen_brand:
                seen_brand.add(e_.signal)
                brand_ev.append(e_)
    res.evidence += _rule_evidence(
        _rules_over(windows), brand_named=any(e_.signal == "message.brand_mention" for e_ in brand_ev)
    )
    intent_ev: dict[str, Evidence] = {}
    # Padding must not hide the ask: the WHOLE input (<= HARD_MAX_MESSAGE_CHARS, linear time) is scored in overlapping
    # windows, not only the head/tail text the rules read. The strongest item per signal/pair stays.
    step = MAX_MESSAGE_CHARS - _INTENT_OVERLAP
    intent_windows = [full[i : i + MAX_MESSAGE_CHARS] for i in range(0, max(1, len(full) - _INTENT_OVERLAP), step)]
    for w in intent_windows:
        for e_ in [*scam_intent(w), *floor_evidence(w)]:
            key = e_.signal + str(e_.observed.get("pair", "")) if isinstance(e_.observed, dict) else e_.signal
            if key not in intent_ev or e_.confidence > intent_ev[key].confidence:
                intent_ev[key] = e_
    res.evidence += list(intent_ev.values())
    res.evidence += script_match_offline(text)
    res.children = [*urls, *phones]
    if urls:
        res.evidence.append(
            Evidence(
                signal="message.contains_url",
                family="message",
                polarity="neutral",
                observed={"count": len(urls), "urls": [defang(display_url(u.value))[:200] for u in urls[:5]]},
                display={"en": "Contains links", "ar": "يحتوي على روابط"},
            )
        )
    if phones:
        res.evidence.append(
            Evidence(
                signal="message.contains_phone",
                family="message",
                polarity="neutral",
                observed={
                    "count": len(phones),
                    "phones": [mask_phone(p.value) for p in phones[:5]],
                },
                display={"en": "Contains phone numbers", "ar": "يحتوي على أرقام هاتف"},
            )
        )
    res.evidence += brand_ev
    return res


def _reg(ctx: SignalContext) -> BrandRegistry:
    r = getattr(ctx, "brands", None)
    return r if isinstance(r, BrandRegistry) else default_registry()


def _by_prefix(ctx: SignalContext, prefixes: tuple[str, ...]) -> list[Evidence]:
    ev = analyze_message(ctx.text or "", _reg(ctx)).evidence
    return [e for e in ev if e.signal.startswith(prefixes)]


@signal(SPEC_RULES)
def run_rules(ctx: SignalContext) -> list[Evidence]:
    return [e for e in analyze_message(ctx.text or "", _reg(ctx)).evidence if e.signal.startswith("message.rule.")]


@signal(SPEC_CHILDREN)
def run_children(ctx: SignalContext) -> list[Evidence]:
    return _by_prefix(ctx, ("message.contains_", "message.limit_exceeded", "message.data_uri"))


@signal(SPEC_BRAND)
def run_brand(ctx: SignalContext) -> list[Evidence]:
    return _by_prefix(ctx, ("message.brand_",))


@signal(SPEC_INTENT)
def run_intent(ctx: SignalContext) -> list[Evidence]:
    t = (ctx.text or "")[:MAX_MESSAGE_CHARS]
    return [*scam_intent(t), *floor_evidence(t)]
