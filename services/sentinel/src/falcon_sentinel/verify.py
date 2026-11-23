"""Pure verifiers for the Sentinel LLM outputs (assess, summarise, propose).

Used by the triage graph at runtime AND by the offline DSPy metric (evals/dspy/roles.py), so the optimiser is scored
by exactly the code that gates model output in production. No I/O, no model calls.
"""

from __future__ import annotations

from typing import Any

from falcon_core.tools.sentinel import DRAFT_TOOLS, ToolError, find_indicator, validate_args

from .llm import AssessOut, ProposeOut, SummaryOut
from .textsafe import vet

MAX_BLOCKS = 5
MAX_ACTIONS = 6
LLM_PROPOSABLE = ("requeue_check", "block_indicator", "draft_takedown", "draft_police_report")


def valid_ids(ids: list[str], view: dict[str, Any]) -> list[str]:
    ok = set(view["evidence_ids"])
    return [i for i in dict.fromkeys(ids) if i in ok]


def verify_reason(out: AssessOut, view: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """(accepted reason or None, text_rejected). A URL/domain/number not in the evidence rejects the text."""
    ids = valid_ids(out.severity_reason.evidence_ids, view)
    en, ar = vet(out.severity_reason.en, view), vet(out.severity_reason.ar, view)
    if ids and en is not None and ar is not None:
        return {"en": en, "ar": ar, "evidence_ids": ids}, False
    return None, bool(ids)


def verify_summary(out: SummaryOut, view: dict[str, Any]) -> tuple[dict[str, Any] | None, bool, int]:
    """(summary without provenance fields or None, text_rejected, claims_offered). Claims that cite no real
    evidence id, or name a foreign URL/domain/number, are dropped."""
    claims = []
    for c in out.claims:
        ids = valid_ids(c.evidence_ids, view)
        text = vet(c.text_en, view)
        if ids and text is not None:
            claims.append({"text_en": text, "evidence_ids": ids})
    en, ar = vet(out.en, view), vet(out.ar, view)
    if en is None or ar is None:
        return None, True, len(out.claims)
    if not claims:
        return None, False, len(out.claims)
    return {"en": en, "ar": ar, "claims": claims}, False, len(out.claims)


def verify_proposals(
    out: ProposeOut, view: dict[str, Any], incident: dict[str, Any]
) -> tuple[list[tuple[str, dict[str, Any], list[str]]], list[dict[str, Any]]]:
    """(accepted (tool, args, evidence_ids), rejected {tool, reason}) with allow-list, citation, argument
    validation, provenance and caps applied. `incident` needs incident_id and indicators."""
    iid = incident["incident_id"]
    accepted: list[tuple[str, dict[str, Any], list[str]]] = []
    rejected: list[dict[str, Any]] = []
    blocks = 0
    for a in out.actions:
        ev_ids = valid_ids(a.why_evidence_ids, view)
        try:
            if a.tool not in LLM_PROPOSABLE:
                raise ToolError("not_allowed", a.tool)
            if not ev_ids:
                raise ToolError("uncited", a.tool)
            args = dict(a.args)
            if a.tool in DRAFT_TOOLS:
                args.setdefault("incident_id", iid)
            if "incident_id" in args and args["incident_id"] != iid:
                raise ToolError("provenance", "foreign incident_id")
            validate_args(a.tool, args)
            if a.tool in ("block_indicator", "requeue_check"):
                key = "indicator" if a.tool == "block_indicator" else "url"
                find_indicator(incident, str(args.get(key, "")))
                blocks += a.tool == "block_indicator"
            if blocks > MAX_BLOCKS or len(accepted) >= MAX_ACTIONS:
                raise ToolError("cap", a.tool)
            accepted.append((a.tool, args, ev_ids))
        except ToolError as exc:
            rejected.append({"tool": a.tool, "reason": exc.reason})
    return accepted, rejected
