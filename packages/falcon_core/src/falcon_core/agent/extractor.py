"""Quarantined extractor (T2): the only LLM that ever sees untrusted text.

No tools. Input is untrusted text (page visible text, a message, an email body), redacted and
spotlighted by the router. Output is a strict schema; anything else (extra keys, unknown enum
values, a brand id not in data/brands.yaml, long strings) is rejected, repaired once, then the
extraction is dropped. The output can only *add* evidence: an ``llm.extraction`` record (weight 0),
``injection.instruction_like_text`` when the text addresses an AI, and ``brand.claimed_not_owned``
when the claimed brand does not own the input's registrable domain.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from falcon_core.agent.brands import load_brand_index
from falcon_core.contracts.evidence import Evidence
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.llm.spotlight import UntrustedText
from falcon_core.prompts import EXTRACTOR_TASK
from falcon_core.tools.util import IdFactory, new_evidence_id


class RequestedData(StrEnum):
    otp = "otp"
    password = "password"  # noqa: S105 - enum label, not a secret
    card_number = "card_number"
    card_cvv = "card_cvv"
    emirates_id = "emirates_id"
    uae_pass = "uae_pass"  # noqa: S105 - enum label
    bank_account = "bank_account"
    personal_info = "personal_info"
    payment = "payment"
    remote_access_app = "remote_access_app"
    click_link = "click_link"
    call_number = "call_number"


class ScriptCategory(StrEnum):
    none = "none"
    bank_account_issue = "bank_account_issue"
    traffic_fine = "traffic_fine"
    delivery_fee = "delivery_fee"
    prize_lottery = "prize_lottery"
    job_offer = "job_offer"
    investment = "investment"
    authority_impersonation = "authority_impersonation"
    account_verification = "account_verification"
    tech_support = "tech_support"
    romance = "romance"
    charity = "charity"
    other = "other"


class Language(StrEnum):
    ar = "ar"
    en = "en"
    arabizi = "arabizi"
    mixed = "mixed"
    other = "other"


class Extraction(BaseModel):
    """Strict extractor output. ``claimed_brand_id`` must be a brands.yaml id."""

    model_config = ConfigDict(extra="forbid")

    claimed_brand_id: str | None = Field(default=None, max_length=64)
    requested_data: list[RequestedData] = Field(default_factory=list, max_length=12)
    script_category: ScriptCategory
    language: Language
    instruction_like: bool

    @field_validator("claimed_brand_id")
    @classmethod
    def _known_brand(cls, v: str | None, info: ValidationInfo) -> str | None:
        if v is None:
            return None
        ctx = info.context or {}
        allowed = ctx.get("brand_ids")
        if allowed is None or v not in allowed:
            raise ValueError("unknown brand id")
        return v

    @field_validator("requested_data")
    @classmethod
    def _dedupe(cls, v: list[RequestedData]) -> list[RequestedData]:
        return sorted(set(v), key=lambda x: x.value)


SourceKind = Literal["page", "message", "email"]
_LABELS: dict[SourceKind, str] = {
    "page": "page_visible_text",
    "message": "message_body",
    "email": "email_body",
}


@dataclass(frozen=True, slots=True)
class ExtractorInput:
    kind: SourceKind
    text: str
    verdict_id: str | None = None
    # For brand.claimed_not_owned: the input's registrable domain (URL / email sender), if any.
    registrable_domain: str | None = None
    extra_texts: Sequence[UntrustedText] = ()  # e.g. page title, email subject (also untrusted)


@dataclass(frozen=True, slots=True)
class ExtractorResult:
    extraction: Extraction | None
    evidence: tuple[Evidence, ...]
    status: str
    route: str
    model: str | None
    ms: int
    cost_usd: float = 0.0
    usage_tokens: int = 0
    meta: Mapping[str, Any] = field(default_factory=dict)


class Extractor:
    def __init__(
        self,
        router: LLMRouter,
        *,
        brand_ids: frozenset[str] | None = None,
        verified_domains: Mapping[str, frozenset[str]] | None = None,
        id_factory: IdFactory = new_evidence_id,
        claim_confidence: float = 0.8,
        instruction_confidence: float = 0.7,
        timeout_s: float = 6.0,
        max_output_tokens: int = 300,
    ) -> None:
        if brand_ids is None or verified_domains is None:
            idx = load_brand_index()
            verified_domains = verified_domains if verified_domains is not None else idx.verified_domains
            brand_ids = brand_ids if brand_ids is not None else idx.ids
        self.router = router
        self.brand_ids = brand_ids
        self.verified_domains = verified_domains
        self._ids = id_factory
        self.claim_confidence = claim_confidence
        self.instruction_confidence = instruction_confidence
        self.timeout_s = timeout_s
        self.max_output_tokens = max_output_tokens

    def _context(self) -> str:
        ids = ", ".join(sorted(self.brand_ids)) or "(none)"
        return f"Allowed brand ids: {ids}"

    async def extract(self, inp: ExtractorInput) -> ExtractorResult:
        t0 = time.monotonic()
        untrusted = [UntrustedText(_LABELS[inp.kind], inp.text), *inp.extra_texts]
        req: JsonRequest[Extraction] = JsonRequest(
            role="extractor",
            task=EXTRACTOR_TASK,
            schema=Extraction,
            context=self._context(),
            untrusted=untrusted,
            max_output_tokens=self.max_output_tokens,
            timeout_s=self.timeout_s,
            validation_context={"brand_ids": self.brand_ids},
            verdict_id=inp.verdict_id,
        )
        res = await self.router.complete_json(req)
        ms = int((time.monotonic() - t0) * 1000)
        source = "llm:extractor"
        if not res.ok or res.value is None:
            err = "canary_leak" if res.canary_leak else (res.status if res.route != "none" else "llm_unavailable")
            ev = Evidence(
                id=self._ids(),
                signal="llm.extraction",
                family="llm",
                observed=None,
                weight=0.0,
                source=source,
                tier="T2",
                latency_ms=ms,
                error=err,
            )
            return ExtractorResult(
                None,
                (ev,),
                res.status,
                res.route,
                res.model,
                ms,
                res.cost_usd,
                res.usage.prompt_tokens + res.usage.output_tokens,
            )
        x = res.value
        evidence: list[Evidence] = [
            Evidence(
                id=self._ids(),
                signal="llm.extraction",
                family="llm",
                observed=x.model_dump(mode="json"),
                weight=0.0,
                source=source,
                tier="T2",
                latency_ms=ms,
            )
        ]
        if x.instruction_like:
            evidence.append(
                Evidence(
                    id=self._ids(),
                    signal="injection.instruction_like_text",
                    family="injection",
                    observed={"detector": "extractor", "source_kind": inp.kind},
                    weight=0.0,
                    polarity="risk",
                    source=source,
                    tier="T2",
                    confidence=self.instruction_confidence,
                    latency_ms=ms,
                )
            )
        if x.claimed_brand_id and inp.registrable_domain:
            owned = self.verified_domains.get(x.claimed_brand_id, frozenset())
            dom = inp.registrable_domain.lower().rstrip(".")
            if dom not in owned:
                evidence.append(
                    Evidence(
                        id=self._ids(),
                        signal="brand.claimed_not_owned",
                        family="brand",
                        observed={
                            "brand_id": x.claimed_brand_id,
                            "domain": dom,
                            "basis": f"{inp.kind}_text",
                        },
                        weight=0.0,
                        polarity="risk",
                        source=source,
                        tier="T2",
                        confidence=self.claim_confidence,
                        latency_ms=ms,
                    )
                )
        return ExtractorResult(
            x,
            tuple(evidence),
            res.status,
            res.route,
            res.model,
            ms,
            res.cost_usd,
            res.usage.prompt_tokens + res.usage.output_tokens,
        )
