"""T3 investigator: an explicit ``plan -> act -> observe -> decide`` state machine (ADR-001).

* The LLM sees structured evidence only (``evidence_view``), never raw page or message text.
* Each PLAN step the LLM emits one ``Action`` JSON, validated by the tool registry (typed args,
  ProvenanceRule). URL/domain arguments may be given as target refs (``u0``, ``d1``) that the
  investigator resolves to the exact on-chain value, so the model never has to copy a URL.
* Budgets (THREAT_MODEL): at most 6 tool calls, 15 s wall time, 8k output tokens per run.
* Output: new evidence (weight 0, tier T3; the arbiter re-scores) plus sanitised trace steps. The
  investigator has no way to set or change a score.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from falcon_core.agent.evidence_view import evidence_item, host_only
from falcon_core.contracts.evidence import Evidence
from falcon_core.contracts.verdict import TraceStep
from falcon_core.llm import metrics as m
from falcon_core.llm.router import JsonRequest, LLMRouter
from falcon_core.prompts import INVESTIGATOR_TASK
from falcon_core.tools.provenance import ProvenanceContext
from falcon_core.tools.registry import SPECS, Action, ToolOutcome, ToolRegistry

MAX_TOOL_CALLS = 6
TIME_BUDGET_S = 15.0
OUTPUT_TOKEN_BUDGET = 8000
PER_CALL_MAX_TOKENS = 700

StopReason = Literal["llm_stop", "max_calls", "time", "tokens", "llm_failed", "no_tools"]


class State(StrEnum):
    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    DECIDE = "decide"
    DONE = "done"


@dataclass(frozen=True, slots=True)
class InvestigationCase:
    evidence: Sequence[Evidence]
    provenance: ProvenanceContext
    input_type: Literal["url", "message", "email", "image"] = "url"
    verdict_id: str | None = None
    first_step: int = 0  # trace step numbering continues the cascade's trace


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    new_evidence: tuple[Evidence, ...]
    trace: tuple[TraceStep, ...]
    tool_calls: int
    stop_reason: StopReason
    route: str
    output_tokens: int
    cost_usd: float
    ms: int
    states: tuple[State, ...] = field(default=())


def _stop_action() -> Action:
    return Action(tool="none", args={}, why_evidence_ids=[], stop=True)


def _summary(text: str) -> str:
    return text[:240]


class Investigator:
    def __init__(
        self,
        router: LLMRouter,
        registry: ToolRegistry,
        *,
        max_tool_calls: int = MAX_TOOL_CALLS,
        time_budget_s: float = TIME_BUDGET_S,
        output_token_budget: int = OUTPUT_TOKEN_BUDGET,
        per_call_max_tokens: int = PER_CALL_MAX_TOKENS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.router = router
        self.registry = registry
        self.max_tool_calls = max_tool_calls
        self.time_budget_s = time_budget_s
        self.output_token_budget = output_token_budget
        self.per_call_max_tokens = per_call_max_tokens
        self._clock = clock

    # --- targets -----------------------------------------------------------------------------

    @staticmethod
    def targets(ctx: ProvenanceContext) -> dict[str, str]:
        """ref -> exact allowed value (u* urls, d* domains, f* fingerprints). Ordered, stable."""
        out: dict[str, str] = {}
        for i, u in enumerate(ctx.url_list):
            out[f"u{i}"] = u
        for i, d in enumerate(ctx.domain_list):
            out[f"d{i}"] = d
        for i, fp in enumerate(sorted(ctx.script_fingerprints)):
            out[f"f{i}"] = fp
        return out

    @staticmethod
    def _resolve(action: Action, targets: dict[str, str]) -> Action:
        args = {k: (targets[v] if isinstance(v, str) and v in targets else v) for k, v in action.args.items()}
        return action.model_copy(update={"args": args})

    def _context(
        self,
        case: InvestigationCase,
        evidence: Sequence[Evidence],
        targets: dict[str, str],
        history: list[dict[str, Any]],
        calls_left: int,
    ) -> str:
        shown_targets = {k: (host_only(v) if k.startswith(("u", "d")) else v) for k, v in targets.items()}
        payload = {
            "input_type": case.input_type,
            "evidence": [evidence_item(e) for e in evidence[:60]],
            "allowed_targets": shown_targets,
            "target_usage": 'pass a target ref such as "u0" or "d0" as the url/domain argument',
            "allowed_brand_ids": sorted(self.registry.brand_ids),
            "tools": self.registry.catalogue(),
            "calls_so_far": history,
            "tool_calls_left": calls_left,
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    # --- run ---------------------------------------------------------------------------------

    async def run(self, case: InvestigationCase) -> InvestigationResult:
        start = self._clock()
        ctx = case.provenance
        known: list[Evidence] = list(case.evidence)
        known_ids = {e.id for e in known}
        new: list[Evidence] = []
        trace: list[TraceStep] = []
        history: list[dict[str, Any]] = []
        seen_calls: set[str] = set()
        states: list[State] = []
        step = case.first_step
        calls = 0
        out_tokens = 0
        cost = 0.0
        route = "none"
        stop: StopReason = "llm_stop"
        action: Action | None = None
        outcome: ToolOutcome | None = None
        state = State.PLAN

        if not self.registry.available():
            state, stop = State.DONE, "no_tools"

        def remaining() -> float:
            return self.time_budget_s - (self._clock() - start)

        while state is not State.DONE:
            states.append(state)
            if state is State.PLAN:
                if remaining() <= 0:
                    state, stop = State.DONE, "time"
                    continue
                tokens_left = self.output_token_budget - out_tokens
                if tokens_left <= 0:
                    state, stop = State.DONE, "tokens"
                    continue
                targets = self.targets(ctx)
                # A plan step can make two provider calls (one repair), so each gets half of what is left.
                call_cap = min(self.per_call_max_tokens, max(1, tokens_left // 2))
                req: JsonRequest[Action] = JsonRequest(
                    role="investigator",
                    task=INVESTIGATOR_TASK,
                    schema=Action,
                    context=self._context(case, known, targets, history, self.max_tool_calls - calls),
                    max_output_tokens=call_cap,
                    timeout_s=remaining(),
                    fallback=_stop_action,
                    verdict_id=case.verdict_id,
                    allow_shadow=False,
                )
                t0 = self._clock()
                res = await self.router.complete_json(req)
                # If a provider reports no usage (some Ollama builds), charge the cap per answered call.
                answered = sum(1 for c in res.calls if c.error is None)
                reported = res.usage.output_tokens
                out_tokens += reported if reported > 0 or answered == 0 else answered * call_cap
                cost += res.cost_usd
                route = res.route if res.route != "none" else route
                step += 1
                if not res.ok or res.value is None:
                    trace.append(
                        TraceStep(
                            step=step,
                            kind="llm",
                            name="investigator.plan",
                            summary=f"no valid action ({res.status}); stopping",
                            ms=int((self._clock() - t0) * 1000),
                        )
                    )
                    state, stop = State.DONE, "llm_failed"
                    continue
                action = self._resolve(res.value, targets)
                if action.stop or action.tool == "none":
                    trace.append(
                        TraceStep(
                            step=step,
                            kind="llm",
                            name="investigator.plan",
                            summary="evidence sufficient; stop",
                            ms=int((self._clock() - t0) * 1000),
                        )
                    )
                    state, stop = State.DONE, "llm_stop"
                    continue
                tool_name = action.tool if action.tool in SPECS else "unknown"
                why = [i for i in action.why_evidence_ids if i in known_ids][:4]
                trace.append(
                    TraceStep(
                        step=step,
                        kind="llm",
                        name="investigator.plan",
                        summary=_summary(f"chose {tool_name}" + (f" because of {', '.join(why)}" if why else "")),
                        ms=int((self._clock() - t0) * 1000),
                    )
                )
                state = State.ACT

            elif state is State.ACT:
                if action is None:  # unreachable: PLAN always sets it
                    state, stop = State.DONE, "llm_failed"
                    continue
                key = json.dumps([action.tool, action.args], sort_keys=True, default=str)
                if key in seen_calls:
                    outcome = ToolOutcome(tool=action.tool[:64], status="rejected", reason="duplicate")
                else:
                    seen_calls.add(key)
                    outcome = await self.registry.execute(action, ctx, timeout_s=max(0.0, remaining()))
                calls += 1
                state = State.OBSERVE

            elif state is State.OBSERVE:
                if outcome is None:  # unreachable: ACT always sets it
                    state = State.DECIDE
                    continue
                if outcome.context is not None:
                    ctx = outcome.context
                for ev in outcome.evidence:
                    if ev.id not in known_ids:
                        known.append(ev)
                        known_ids.add(ev.id)
                        new.append(ev)
                tool_name = outcome.tool if outcome.tool in SPECS else "unknown"
                step += 1
                detail = f" ({outcome.reason})" if outcome.reason else ""
                trace.append(
                    TraceStep(
                        step=step,
                        kind="tool",
                        name=tool_name,
                        summary=_summary(f"{tool_name}: {outcome.status}{detail}, {len(outcome.evidence)} new"),
                        evidence_added=[e.id for e in outcome.evidence] or None,
                        ms=outcome.ms,
                    )
                )
                history.append(
                    {
                        "tool": tool_name,
                        "status": outcome.status,
                        "reason": outcome.reason,
                        "evidence_added": [e.id for e in outcome.evidence],
                    }
                )
                state = State.DECIDE

            elif state is State.DECIDE:
                if calls >= self.max_tool_calls:
                    state, stop = State.DONE, "max_calls"
                elif remaining() <= 0:
                    state, stop = State.DONE, "time"
                elif out_tokens >= self.output_token_budget:
                    state, stop = State.DONE, "tokens"
                else:
                    state = State.PLAN

        self.router.metrics.observe(m.AGENT_STEPS, float(calls))
        return InvestigationResult(
            new_evidence=tuple(new),
            trace=tuple(trace),
            tool_calls=calls,
            stop_reason=stop,
            route=route,
            output_tokens=out_tokens,
            cost_usd=cost,
            ms=int((self._clock() - start) * 1000),
            states=tuple(states),
        )
