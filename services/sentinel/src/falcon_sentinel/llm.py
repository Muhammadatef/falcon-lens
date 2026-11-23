"""LLM access for the Sentinel graph.

The graph codes to the `LLMClient` protocol only (agent-core's router in falcon_core.llm will satisfy it).
Here: a deterministic stub (tests, offline demo) and a thin adapter to an OpenAI-compatible endpoint
(the falcon_core router: cloud or local) for live runs. Outputs are parsed with pydantic and
get ONE repair retry; the model never sets a score and only ever sees structured evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from falcon_core.llm import JsonRequest, LLMRouter

# Sentinel task -> compiled prompt name (falcon_core.prompts.compiled); hand-written SYSTEM is the fallback.
_COMPILED = {"assess": "sentinel_assess", "summarise": "sentinel_summarise", "propose": "sentinel_propose"}
END_TOKENS = ("<|end_message|>", "<|im_end|>", "<|endoftext|>")


class LLMClient(Protocol):
    route: str  # "cloud" | "local" (reported in incident.summary.model_route)

    async def complete_json(
        self, *, role: str, system: str, user_json: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]: ...


class LLMOutputError(Exception):
    """Model output was not valid after the repair retry."""


class LLMUnavailable(LLMOutputError):
    """The model could not be reached or answered with an error (HTTP, connection, timeout).
    A subclass of LLMOutputError so every node falls back to the template path; it is never retried."""


class BudgetExceeded(Exception):
    pass


# ------------------------------------------------------------------ output schemas


class Reason(BaseModel):
    model_config = ConfigDict(extra="ignore")
    en: str = Field(min_length=1, max_length=600)
    ar: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(default_factory=list)


class AssessOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    severity_reason: Reason


class ClaimOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text_en: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list)


class SummaryOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    en: str = Field(min_length=1, max_length=1500)
    ar: str = Field(min_length=1, max_length=1500)
    claims: list[ClaimOut] = Field(default_factory=list)


class ActionOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    why_evidence_ids: list[str] = Field(default_factory=list)


class ProposeOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    actions: list[ActionOut] = Field(default_factory=list, max_length=10)


def clean_text(raw: str) -> str:
    for t in END_TOKENS:
        raw = raw.replace(t, "")
    raw = raw.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.S)
    return m.group(1) if m else raw


def estimate_tokens(*objs: Any) -> int:
    return sum(len(json.dumps(o, ensure_ascii=False, default=str)) for o in objs) // 4 + 1


async def structured[M: BaseModel](
    llm: LLMClient,
    model: type[M],
    *,
    system: str,
    user_json: dict[str, Any],
    on_tokens: Callable[[int], None] | None = None,
    on_usage: Callable[[int, int, bool], None] | None = None,
) -> M:
    """complete_json -> pydantic, with one repair retry that feeds the validation error back."""
    complete_model = getattr(llm, "complete_model", None)
    if complete_model is not None:  # router-backed client: redaction, repair and budgets live in the router
        return await complete_model(model, system=system, user_json=user_json, on_tokens=on_tokens, on_usage=on_usage)  # type: ignore[no-any-return]
    schema = model.model_json_schema()
    last_err = ""
    for attempt in range(2):
        payload = (
            user_json
            if attempt == 0
            else {
                **user_json,
                "repair": f"Previous output was invalid: {last_err[:300]}. Return only valid JSON matching the schema.",
            }
        )
        try:
            data = await llm.complete_json(role="sentinel", system=system, user_json=payload, schema=schema)
        except LLMUnavailable:
            raise
        except LLMOutputError as exc:  # unparseable text: one repair retry like a schema failure
            last_err = str(exc)
            continue
        if on_tokens:
            on_tokens(estimate_tokens(payload, data))
        if on_usage:
            on_usage(estimate_tokens(payload), estimate_tokens(data), attempt > 0)
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            last_err = str(exc.errors()[0]["msg"]) + " @" + ".".join(str(x) for x in exc.errors()[0]["loc"])
    raise LLMOutputError(last_err)


# ------------------------------------------------------------------ OpenAI-compatible adapter


class RouterLLM:
    """The only live LLM client: every Sentinel call goes through falcon_core.llm.router.LLMRouter, which applies
    normalise -> redact -> (spotlight) -> canary -> one repair retry, honours sovereign mode (no cloud route
    without a key or in sovereign mode) and falls back cloud -> local. Failures raise LLMUnavailable/LLMOutputError
    so every node degrades to its template."""

    def __init__(self, router: LLMRouter, max_output_tokens: int = 1200) -> None:
        self.router = router
        self.max_output_tokens = max_output_tokens
        self._last_route: str | None = None

    @property
    def route(self) -> str:
        """Route of the latest call (cloud | local); the planned primary route before any call."""
        return self._last_route or self.router.primary_route("sentinel")

    async def complete_model[M: BaseModel](
        self,
        model: type[M],
        *,
        system: str,
        user_json: dict[str, Any],
        on_tokens: Callable[[int], None] | None = None,
        on_usage: Callable[[int, int, bool], None] | None = None,
    ) -> M:
        res = await self.router.complete_json(
            JsonRequest(
                role="sentinel",
                compiled=_COMPILED.get(str(user_json.get("task"))),
                task=system,
                schema=model,
                context=json.dumps(user_json, ensure_ascii=False, default=str),
                max_output_tokens=self.max_output_tokens,
            )
        )
        if res.route != "none":
            self._last_route = res.route
        if on_tokens:  # count tokens even when the output turns out unusable
            on_tokens(res.usage.input_tokens + res.usage.output_tokens)
        if on_usage:
            on_usage(res.usage.input_tokens, res.usage.output_tokens, len(res.calls) > 1)
        if res.ok and res.value is not None:
            return res.value
        if res.route == "none" or all(c.error for c in res.calls):
            raise LLMUnavailable(res.error or "no route answered")
        raise LLMOutputError(res.error or "invalid model output")


# ------------------------------------------------------------------ deterministic stub


class StubLLM:
    """Deterministic, offline. Reads the evidence view in user_json and answers from it (never invents ids).
    `overrides[task]` can return custom (or invalid) output to exercise the verifier and repair paths."""

    route = "local"

    def __init__(self, overrides: dict[str, Callable[[dict[str, Any]], Any]] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self, *, role: str, system: str, user_json: dict[str, Any], schema: dict[str, Any]
    ) -> dict[str, Any]:
        if role != "sentinel":
            raise ValueError(role)
        self.calls.append({"task": user_json.get("task"), "repair": "repair" in user_json})
        task = str(user_json.get("task"))
        if task in self.overrides:
            out = self.overrides[task](user_json)
            if isinstance(out, Exception):
                raise out
            return dict(out)
        ev = user_json["evidence"]
        ids = ev["evidence_ids"]
        rule_ids = [i for i in ids if i.startswith("rule:")]
        event_ids = [i for i in ids if i.startswith("evt_")]
        brand = ev.get("brand_id") or "unknown"
        n_dom = len([i for i in ev["indicators"] if i["kind"] == "domain"])
        if task == "assess":
            return {
                "severity_reason": {
                    "en": f"{ev['type']} for brand {brand}: {n_dom} domains matched {', '.join(ev['rule_ids'])}.",
                    "ar": f"حادثة من نوع {ev['type']} للعلامة {brand}: تطابقت {n_dom} نطاقات مع القواعد {', '.join(ev['rule_ids'])}.",
                    "evidence_ids": (rule_ids + event_ids[:3]),
                }
            }
        if task == "summarise":
            return {
                "en": f"Sentinel linked {n_dom} lookalike domains for {brand} into one {ev['type']} incident.",
                "ar": f"ربط الحارس {n_dom} نطاقات مشابهة للعلامة {brand} في حادثة واحدة من نوع {ev['type']}.",
                "claims": [
                    {
                        "text_en": f"Rules {', '.join(ev['rule_ids'])} fired.",
                        "evidence_ids": rule_ids[:2],
                    },
                    {
                        "text_en": f"{n_dom} domains share correlation keys.",
                        "evidence_ids": event_ids[:4],
                    },
                ],
            }
        if task == "propose":
            doms = [i for i in ev["indicators"] if i["kind"] == "domain"]
            actions: list[dict[str, Any]] = []
            if doms:
                actions.append(
                    {
                        "tool": "block_indicator",
                        "args": {"indicator": doms[0]["value_defanged"], "ttl_hours": 72},
                        "why_evidence_ids": rule_ids[:1] + event_ids[:1],
                    }
                )
                actions.append(
                    {
                        "tool": "draft_takedown",
                        "args": {"incident_id": ev["incident_id"], "recipient_kind": "registrar"},
                        "why_evidence_ids": rule_ids[:1],
                    }
                )
            return {"actions": actions}
        raise ValueError(f"unknown task {task}")
