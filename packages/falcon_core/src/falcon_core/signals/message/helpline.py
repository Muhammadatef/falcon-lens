"""Fake helpline numbers: ``brand.unofficial_contact_number`` (docs/design/HUNTER.md §7, task T-036).

The text names a registered brand and gives a UAE phone number that is on no brand's verified
``official_contacts`` list (data/brands.yaml). Rules:
- a number that IS on the list emits nothing: caller ID can be spoofed, so a match is never trust;
- a brand with no verified numbers emits nothing (an incomplete registry must not raise false alarms);
- a number with no brand named emits nothing.
Evidence carries the masked number (plus a keyed HMAC id only when FL_EVIDENCE_HMAC_KEY is set), never the number
or a bare hash. Weight 0 until an owner-approved fit
(docs/SCORING.md §2 note); the arbiter treats a name missing from params.yaml as weight 0.

``helpline_evidence`` is pure (no network, no logging) and serves message and email bodies (T1, through
``analyze_message``) and sandbox page text (T2, called by the page pipeline with ``tier="T2"``).
"""

from __future__ import annotations

import re

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.brands.contacts import extract_numbers, mask_number, number_id
from falcon_core.signals.brands.registry import Brand, BrandRegistry, default_registry
from falcon_core.signals.limits import HARD_MAX_MESSAGE_CHARS
from falcon_core.signals.message.normalize import MAX_MESSAGE_CHARS, normalize
from falcon_core.signals.url.textutil import compact

SIGNAL = "brand.unofficial_contact_number"
MAX_REPORTED = 5

SPEC = SignalSpec(
    name="brand.contact_number",
    family="brand",
    tier="T1",
    input_types=("message", "email", "image"),
    timeout_ms=100,
    network="none",
    emits=(SIGNAL,),
)

DISPLAY = {
    "en": "Gives a phone number that is not on the organisation's official list",
    "ar": "يذكر رقم هاتف غير مدرج في القائمة الرسمية للجهة",
}


def named_brands(text: str, reg: BrandRegistry) -> list[Brand]:
    """Registered brands the text names (same matching as ``message.brand_mention``)."""
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
    return found


def helpline_evidence(
    text: str,
    reg: BrandRegistry,
    brands: list[Brand] | None = None,
    tier: str = "T1",
) -> list[Evidence]:
    """At most one evidence item for ``text``; ``brands`` may be passed when the caller already matched them."""
    named = brands if brands is not None else named_brands(text[:MAX_MESSAGE_CHARS], reg)
    claimed = [b for b in named if b.official_contacts]
    if not claimed:
        return []
    unofficial = [e164 for e164, _span in extract_numbers(text) if not reg.number_brands(e164)]
    if not unofficial:
        return []
    return [
        Evidence(
            signal=SIGNAL,
            family="brand",
            polarity="risk",
            observed={
                "brands": [b.brand_id for b in claimed],
                "numbers": [_number(n) for n in unofficial[:MAX_REPORTED]],
                "count": len(unofficial),
            },
            display=dict(DISPLAY),
            source="registry",
            tier=tier,
            confidence=0.7,
        )
    ]


def _number(e164: str) -> dict[str, str]:
    out = {"masked": mask_number(e164)}
    if (nid := number_id(e164)) is not None:
        out["id"] = nid  # keyed HMAC, only when FL_EVIDENCE_HMAC_KEY is set; never a bare hash
    return out


def _reg(ctx: SignalContext) -> BrandRegistry:
    r = getattr(ctx, "brands", None)
    return r if isinstance(r, BrandRegistry) else default_registry()


@signal(SPEC)
def run(ctx: SignalContext) -> list[Evidence]:
    return helpline_evidence((ctx.text or "")[:HARD_MAX_MESSAGE_CHARS], _reg(ctx))
