"""Glue between the injection detector and the LLM stages (docs/THREAT_MODEL.md, prompt injection).

* ``prepare_untrusted``: run the detector over the text the extractor is about to see, remove the
  flagged spans (``neutralise``) and return the risk evidence. The extractor still gets spotlighted,
  datamarked text from the router; this is an extra layer so an obedient model never sees the order.
* ``llm_failure_evidence``: an extraction dropped because the reply leaked the canary is itself a
  manipulation signal. Without this an attacker could make the extractor fail on purpose and lose the
  brand-claim evidence it would otherwise have produced.

Both only ever *add* risk evidence; nothing here can lower a score.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from falcon_core.contracts.evidence import Evidence as ContractEvidence
from falcon_core.signals.base import Evidence
from falcon_core.signals.injection import SIGNAL, InjectionReport, Segment, detect, neutralise


@dataclass(frozen=True, slots=True)
class PreparedText:
    text: str  # what the extractor may see
    report: InjectionReport  # detector report over the original text
    removed: bool


def prepare_untrusted(text: str) -> PreparedText:
    cleaned, report = neutralise(text)
    return PreparedText(cleaned, report, cleaned != text)


def page_report(segments: Sequence[Segment], hidden_chars: int | None = None, visible_chars: int | None = None) -> InjectionReport:
    return detect(segments, hidden_text_chars=hidden_chars, visible_text_chars=visible_chars)


def llm_failure_evidence(evidence: Iterable[ContractEvidence], tier: str = "T2") -> list[ContractEvidence]:
    """Map extractor failures caused by manipulation (canary leak) to injection risk evidence."""
    out: list[ContractEvidence] = []
    for ev in evidence:
        if ev.signal == "llm.extraction" and ev.error == "canary_leak":
            base = Evidence(
                signal=SIGNAL,
                family="injection",
                observed={"detector": "canary", "role": "extractor"},
                polarity="risk",
                source="computed",
                tier=tier,
                confidence=1.0,
            )
            out.append(ContractEvidence.model_validate(base.to_dict()))
    return out
