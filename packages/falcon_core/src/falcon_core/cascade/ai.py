"""Glue between the cascade and the LLM agents (extractor, investigator, responder) and the T1 model.

Security architecture (L1 decision):

* H1 never depends on an LLM. Brand claims come from deterministic page signals (``cascade.page``);
  an extractor claim is *additional*, risk-only evidence (``scoring.hard_rules.h1_brand_mismatch`` ignores
  untrusted-origin claims).
* Everything an agent returns is normalised by :func:`risk_only`: it keeps its untrusted source tag,
  never carries trust polarity, a weight or a hard-rule tag, so the arbiter alone decides.
* The cascade adds agent evidence next to the deterministic evidence, never instead of it, so
  ``score(det + llm) >= score(det)`` holds for any extractor output (tested).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from falcon_core.agent.extractor import Extractor as AgentExtractor
from falcon_core.agent.extractor import ExtractorInput
from falcon_core.cascade.evidence import from_signal
from falcon_core.cascade.models import SandboxFeatures
from falcon_core.contracts.evidence import Evidence as ContractEvidence
from falcon_core.llm.spotlight import UntrustedText
from falcon_core.scoring.evidence import Evidence, from_contract, to_contract, untrusted_origin
from falcon_core.signals.base import Evidence as SignalEvidence
from falcon_core.signals.url.canonical import canonicalize

log = logging.getLogger("falcon.cascade.ai")

InjectionDetect = Callable[[str], Sequence[SignalEvidence]]


def risk_only(ev: Evidence) -> Evidence:
    """Normalise agent-produced evidence: no trust polarity, no weight, no hard-rule tag."""
    pol = "neutral" if ev.polarity == "trust" else ev.polarity
    return replace(ev, weight=0.0, polarity=pol, hard_rule=None)


def to_scoring(ev: ContractEvidence) -> Evidence:
    return from_contract(ev.model_dump(mode="json"))


def to_contract_model(ev: Evidence) -> ContractEvidence:
    return ContractEvidence.model_validate(to_contract(ev))


def load_injection_detector() -> InjectionDetect | None:
    """``signals.injection.detect`` (PR #41) when present; None keeps the cascade working without it."""
    import importlib

    try:
        detect = importlib.import_module("falcon_core.signals.injection").detect
    except (ImportError, AttributeError):
        return None

    def run(text: str) -> Sequence[SignalEvidence]:
        out: Sequence[SignalEvidence] = detect(text).evidence("T2")
        return out

    return run


def injection_evidence(detect_fn: InjectionDetect | None, *texts: str) -> list[Evidence]:
    """Deterministic injection findings on untrusted text. Risk-only, never obeyed."""
    if detect_fn is None:
        return []
    out: list[Evidence] = []
    for t in texts:
        if not t:
            continue
        try:
            out.extend(risk_only(from_signal(e)) for e in detect_fn(t))
        except Exception as exc:  # noqa: BLE001 - a detector bug must not break the check
            log.warning("injection detector failed: %s", type(exc).__name__)
    return out


class Extracted(list[Evidence]):
    """Extractor evidence plus the route of *this* call (no shared state between concurrent checks)."""

    route: str = "none"


class AgentExtractorAdapter:
    """``cascade.ports.Extractor`` over the quarantined LLM extractor.

    The injection detector is deliberately NOT called here: the cascade runs it independently, before
    this call, so a slow or failing provider can never discard detector findings.
    """

    def __init__(self, extractor: AgentExtractor) -> None:
        self.extractor = extractor

    async def extract(self, features: SandboxFeatures, verdict_id: str) -> Extracted:
        reg = canonicalize(features.final_url).registrable if features.final_url else None
        inp = ExtractorInput(
            kind="page",
            text=features.visible_text,
            verdict_id=verdict_id,
            registrable_domain=reg or None,
            extra_texts=(UntrustedText("page_title", features.title),) if features.title else (),
        )
        res = await self.extractor.extract(inp)
        out = Extracted(risk_only(to_scoring(e)) for e in res.evidence)
        out.route = res.route
        return out

    async def extract_text(
        self, kind: str, text: str, verdict_id: str, registrable_domain: str | None = None
    ) -> Extracted:
        """Message / email body."""
        if kind not in ("message", "email"):
            raise ValueError(kind)
        res = await self.extractor.extract(
            ExtractorInput(kind=kind, text=text, verdict_id=verdict_id, registrable_domain=registrable_domain)  # type: ignore[arg-type]
        )
        out = Extracted(risk_only(to_scoring(e)) for e in res.evidence)
        out.route = res.route
        return out


def assert_llm_cannot_lower(det: Sequence[Evidence], llm: Sequence[Evidence]) -> bool:
    """Structural check used by tests and the engine: every agent item is untrusted-origin or risk-only."""
    return all(untrusted_origin(e) or e.polarity != "trust" for e in llm) and not any(
        e.id in {d.id for d in det} for e in llm
    )


ToolFn = Callable[[str], Awaitable[Sequence[ContractEvidence]]]


def signal_backend(name: str, ctx_factory: Callable[[str], Any], registry: Mapping[str, Any]) -> ToolFn | None:
    """Wrap a registered signal as an investigator tool backend (domain or URL in, contract evidence out).

    The registry re-stamps ids/tier and the arbiter owns weights; the backend only reports observations.
    """
    entry = registry.get(name)
    if entry is None:
        return None
    _spec, fn = entry

    async def run(value: str) -> Sequence[ContractEvidence]:
        out: list[ContractEvidence] = []
        for e in await fn(ctx_factory(value)):
            d = e.to_dict()
            d.update(weight=0.0, polarity="neutral", hard_rule=None)
            out.append(ContractEvidence.model_validate(d))
        return out

    return run
