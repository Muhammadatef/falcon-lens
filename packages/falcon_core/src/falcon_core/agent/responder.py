"""Responder + faithfulness verifier (SCORING §5).

The responder LLM writes at most three bilingual reasons (Arabic written natively, simple) from the
arbiter-weighted evidence, structured only. The verifier rejects the whole LLM answer if any reason
cites no evidence, cites an id that does not exist or errored, cites evidence that contradicts the
verdict's direction, or breaks the product rules ("safe" wording, links/domains, HTML, scores).
On rejection the template reasons from ``scoring.reasons`` are returned (``generated_by=template``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from falcon_core.agent.evidence_view import evidence_item
from falcon_core.contracts.evidence import Evidence
from falcon_core.contracts.verdict import Reason
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.prompts import RESPONDER_TASK

VerdictLabel = Literal["dangerous", "suspicious", "no_warning_signs"]
MAX_REASONS = 3

_ARABIC_RE = re.compile(r"[؀-ۿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SAFE_EN_RE = re.compile(r"(?i)\bsafe\b")
_SAFE_AR_RE = re.compile(r"(?<!\w)(?:آمن|آمنة|آمنا|امن|امنة)(?!\w)")
_LINK_RE = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]*://|\bwww\.|\b[a-z0-9-]+\.(?:[a-z]{2,24})\b)")
_FORBIDDEN_CHARS = set("<>%")
_SCORE_RE = re.compile(r"(?i)\b(?:score|probability)\b|نسبة|درجة الخطورة")


class ReasonDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ar: str = Field(min_length=1, max_length=220)
    en: str = Field(min_length=1, max_length=220)
    evidence_ids: list[str] = Field(min_length=1, max_length=6)


class ResponderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasons: list[ReasonDraft] = Field(min_length=1, max_length=MAX_REASONS)


def _text_errors(i: int, d: ReasonDraft) -> list[str]:
    errs: list[str] = []
    if not _ARABIC_RE.search(d.ar):
        errs.append(f"reason[{i}].ar is not Arabic")
    if not _LATIN_RE.search(d.en):
        errs.append(f"reason[{i}].en is not English")
    for lang, text in (("ar", d.ar), ("en", d.en)):
        if _SAFE_EN_RE.search(text) or _SAFE_AR_RE.search(text):
            errs.append(f"reason[{i}].{lang} says safe")
        if _LINK_RE.search(text):
            errs.append(f"reason[{i}].{lang} contains a link or domain")
        if _FORBIDDEN_CHARS & set(text):
            errs.append(f"reason[{i}].{lang} contains forbidden characters")
        if _SCORE_RE.search(text):
            errs.append(f"reason[{i}].{lang} mentions a score")
    return errs


def verify_reasons(drafts: Sequence[ReasonDraft], evidence: Sequence[Evidence], verdict: VerdictLabel) -> list[str]:
    """Return a list of problems; empty means the reasons are faithful to the evidence."""
    by_id = {e.id: e for e in evidence}
    errs: list[str] = []
    if not 1 <= len(drafts) <= MAX_REASONS:
        errs.append("reason count out of range")
    for i, d in enumerate(drafts):
        if not d.evidence_ids:
            errs.append(f"reason[{i}] cites no evidence")
            continue
        cited: list[Evidence] = []
        for eid in d.evidence_ids:
            ev = by_id.get(eid)
            if ev is None:
                errs.append(f"reason[{i}] cites unknown id")
            elif ev.error is not None:
                errs.append(f"reason[{i}] cites errored evidence")
            else:
                cited.append(ev)
        if cited:
            if verdict == "no_warning_signs":
                if any(e.weight > 0 for e in cited):
                    errs.append(f"reason[{i}] cites risk evidence for a no-warning verdict")
            elif not any(e.weight > 0 or e.hard_rule for e in cited):
                errs.append(f"reason[{i}] cites no risk evidence for a warning verdict")
        errs.extend(_text_errors(i, d))
    return errs


@dataclass(frozen=True, slots=True)
class ResponderInput:
    verdict: VerdictLabel
    evidence: Sequence[Evidence]  # arbiter-weighted (weight / hard_rule filled)
    template_reasons: Sequence[Reason]  # scoring.reasons.contract_reasons(...), the fallback
    verdict_id: str | None = None
    degraded: bool = False


@dataclass(frozen=True, slots=True)
class ResponderResult:
    reasons: tuple[Reason, ...]
    generated_by: Literal["llm", "template"]
    route: str
    status: str
    verifier_errors: tuple[str, ...] = ()
    cost_usd: float = 0.0


class Responder:
    def __init__(self, router: LLMRouter, *, timeout_s: float = 6.0, max_output_tokens: int = 700):
        self.router = router
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens

    @staticmethod
    def _template(
        inp: ResponderInput,
        status: str,
        route: str = "none",
        errs: Sequence[str] = (),
        cost: float = 0.0,
    ) -> ResponderResult:
        reasons = tuple(r.model_copy(update={"generated_by": "template"}) for r in inp.template_reasons[:MAX_REASONS])
        return ResponderResult(reasons, "template", route, status, tuple(errs), cost)

    def _context(self, inp: ResponderInput) -> str:
        relevant = [e for e in inp.evidence if e.error is None and (e.weight != 0 or e.hard_rule)]
        relevant.sort(key=lambda e: (e.hard_rule is None, -abs(e.weight)))
        payload = {
            "verdict": inp.verdict,
            "degraded": inp.degraded,
            "evidence": [evidence_item(e, with_weight=True) for e in relevant[:20]],
            "template_reasons": [
                {"en": r.en, "ar": r.ar, "evidence_ids": r.evidence_ids} for r in inp.template_reasons
            ],
            "instructions": "Improve on the template reasons if you can, staying faithful to them.",
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    async def respond(self, inp: ResponderInput) -> ResponderResult:
        if not inp.template_reasons or inp.degraded:
            # Nothing to explain, or a degraded verdict: the fixed wording is the honest one.
            return self._template(inp, "skipped")
        req: JsonRequest[ResponderOutput] = JsonRequest(
            role="responder",
            task=RESPONDER_TASK,
            schema=ResponderOutput,
            context=self._context(inp),
            max_output_tokens=self.max_output_tokens,
            timeout_s=self.timeout_s,
            verdict_id=inp.verdict_id,
        )
        res = await self.router.complete_json(req)
        if not res.ok or res.value is None:
            return self._template(inp, res.status, res.route, [res.error or res.status], res.cost_usd)
        errs = verify_reasons(res.value.reasons, inp.evidence, inp.verdict)
        if errs:
            return self._template(inp, "rejected", res.route, errs, res.cost_usd)
        reasons = tuple(
            Reason(
                ar=d.ar.strip(),
                en=d.en.strip(),
                evidence_ids=list(dict.fromkeys(d.evidence_ids)),
                generated_by="llm",
            )
            for d in res.value.reasons
        )
        return ResponderResult(reasons, "llm", res.route, res.status, (), res.cost_usd)
