"""Agent run trace (contracts/agent_trace.schema.json).

Every graph node execution and every graph invocation ("run") is appended to the append-only table
`agent_trace_steps`. Rows carry only template fields: node names, counts, enums, tool names, evidence ids and
durations. They never carry LLM prompts or outputs, raw text or live URLs (summaries pass `safe_text`, which
applies the textsafe URL/domain rules). Tracing never breaks triage: write errors are logged and swallowed.

`assemble_trace(rows)` folds the rows into the contract document (latest row per step wins, so a step is first
written as `running` and then re-appended with its final state).
"""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from falcon_core.tools.sentinel import (
    TOOL_MODE,
    ToolContext,
    ToolError,
    ToolResult,
    run_action,
    run_read,
)

from .textsafe import DOMAIN_RE, URL_RE, defang_hosts

log = logging.getLogger("falcon.sentinel.trace")

NODES = ("enrich", "compare", "assess", "summarise", "propose", "act")
MAX_TOOL_EVIDENCE = 20

CUR_RUN: contextvars.ContextVar[str | None] = contextvars.ContextVar("fl_trace_run", default=None)
CUR_STEP: contextvars.ContextVar[StepRec | None] = contextvars.ContextVar("fl_trace_step", default=None)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def safe_text(text: str) -> str:
    """Summaries are built from counts and enums; still, never let a URL or a live domain through."""
    if URL_RE.search(text):
        return "(redacted)"
    return defang_hosts(text, set())[:300] if DOMAIN_RE.search(text) else text[:300]


@dataclass
class StepRec:
    """Collector for one node execution (tools called, LLM usage)."""

    tools: list[dict[str, Any]] = field(default_factory=list)
    llm: dict[str, Any] | None = None
    fallback: bool = False
    rule_fallback: bool = False

    def use_llm(self, route: str, model: str) -> dict[str, Any]:
        if self.llm is None:
            self.llm = {
                "route": route,
                "model": model[:80],
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "repaired": False,
                "fallback_template": False,
            }
        return self.llm


def _tool_row(name: str, mode: str, ok: bool, evidence_ids: list[str], t0: float) -> dict[str, Any]:
    return {
        "name": name,
        "mode": mode,
        "status": "ok" if ok else "error",
        "evidence_ids": evidence_ids[:MAX_TOOL_EVIDENCE],
        "duration_ms": int((time.monotonic() - t0) * 1000),
    }


async def traced_read(ctx: ToolContext, tool: str, args: dict[str, Any]) -> ToolResult:
    t0, rec = time.monotonic(), CUR_STEP.get()
    try:
        res = await run_read(ctx, tool, args)
    except BaseException:
        if rec is not None:
            rec.tools.append(_tool_row(tool, "read", False, [], t0))
        raise
    if rec is not None:
        rec.tools.append(_tool_row(tool, "read", True, [], t0))
    return res


async def traced_action(
    ctx: ToolContext,
    tool: str,
    args: dict[str, Any],
    *,
    incident_id: str,
    action_id: str,
    evidence_ids: list[str],
    actor: str = "sentinel",
) -> ToolResult:
    t0, rec = time.monotonic(), CUR_STEP.get()
    mode = TOOL_MODE.get(tool, "internal_auto")
    try:
        res = await run_action(
            ctx, tool, args, incident_id=incident_id, action_id=action_id, evidence_ids=evidence_ids, actor=actor
        )
    except ToolError:
        if rec is not None:
            rec.tools.append(_tool_row(tool, mode, False, evidence_ids, t0))
        raise
    if rec is not None:
        rec.tools.append(_tool_row(tool, mode, bool(res.ok), evidence_ids, t0))
    return res


# ------------------------------------------------------------------ summaries (template fields only)


def summarise_step(node: str, out: dict[str, Any], rec: StepRec, status: str, pending: int) -> tuple[str, str]:
    if status == "failed":
        return "The step failed; it will be retried or resumed.", "فشلت الخطوة وستُعاد المحاولة أو تُستأنف."
    if status == "interrupted":
        return (
            f"Waiting for a human to decide on {pending} external draft(s). Nothing is sent before approval.",
            f"بانتظار قرار بشري على {pending} مسودة خارجية. لا يُرسل شيء قبل الموافقة.",
        )
    n_tools = len(rec.tools)
    if node == "enrich":
        ev = out.get("evidence", {})
        n_ev, n_ind = len(ev.get("evidence_ids", [])), len(ev.get("indicators", []))
        return (
            f"Gathered context with {n_tools} read tools: {n_ind} indicators, {n_ev} evidence ids.",
            f"جُمع السياق بـ {n_tools} أدوات قراءة: {n_ind} مؤشرات و{n_ev} معرّف دليل.",
        )
    if node == "compare":
        c = out.get("evidence", {}).get("comparison", {})
        rd, pi = int(c.get("related_domain_count", 0)), int(c.get("past_incident_count", 0))
        return (
            f"Compared indicators: {rd} related domains, {pi} past incidents. Deterministic, no model.",
            f"قورنت المؤشرات: {rd} نطاقات مرتبطة و{pi} حوادث سابقة. بلا نموذج.",
        )
    if node in ("assess", "summarise"):
        what_en, what_ar = ("severity reason", "سبب الخطورة") if node == "assess" else ("summary", "الملخص")
        if rec.fallback:
            return (
                f"The {what_en} was written from a template (model output not accepted).",
                f"كُتب {what_ar} من قالب (لم يُقبل مخرج النموذج).",
            )
        return (
            f"The {what_en} was written by the model and checked against the evidence.",
            f"كتب النموذج {what_ar} وجرى التحقق منه مقابل الأدلة.",
        )
    if node == "propose" and rec.rule_fallback:
        return (
            "No valid model proposal: a rule-based takedown draft was queued. It needs human approval.",
            "لا مقترح صالحاً من النموذج، فأُضيفت مسودة بلاغ وفق القواعد. تحتاج موافقة بشرية.",
        )
    if node == "propose":
        n, r = len(out.get("proposals", [])), len(out.get("rejected", []))
        return (
            f"Proposed {n} actions; {r} model proposals were rejected by the validator.",
            f"اقتُرحت {n} إجراءات، ورفض المدقق {r} من مقترحات النموذج.",
        )
    n_ok = sum(1 for t in rec.tools if t["status"] == "ok")
    return (
        f"Ran {n_ok} automatic actions; {pending} drafts still wait for approval.",
        f"نُفذت {n_ok} إجراءات تلقائية وما زالت {pending} مسودات بانتظار الموافقة.",
    )


# ------------------------------------------------------------------ recorder


class TraceRecorder:
    def __init__(self, repo: Any, clock: Any) -> None:
        self.repo = repo
        self.clock = clock
        self._seq: dict[str, int] = {}

    async def _append(self, row: dict[str, Any]) -> None:
        try:
            await self.repo.trace_append(row)
        except Exception:  # noqa: BLE001 - tracing must never break triage
            log.exception("trace write failed")

    async def next_seq(self, iid: str) -> int:
        if iid not in self._seq:
            try:
                rows = await self.repo.trace_list(iid)
            except Exception:  # noqa: BLE001
                rows = []
            self._seq[iid] = max((int(r["seq"]) for r in rows if r.get("seq")), default=0)
        self._seq[iid] += 1
        return self._seq[iid]

    def _row(self, iid: str, run_id: str | None, kind: str, seq: int | None, doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "incident_id": iid,
            "thread_id": iid,
            "run_id": run_id or "run_none",
            "seq": seq,
            "kind": kind,
            "at": self.clock(),
            "doc": doc,
        }

    async def run_start(self, iid: str, trigger: str, decision: dict[str, Any] | None = None) -> str:
        run_id = "run_" + uuid.uuid4().hex[:16]
        await self._append(
            self._row(iid, run_id, "run", None, {"phase": "start", "trigger": trigger, "decision": decision})
        )
        return run_id

    async def run_end(self, iid: str, run_id: str, status: str, interrupt: dict[str, Any] | None) -> None:
        await self._append(
            self._row(iid, run_id, "run", None, {"phase": "end", "status": status, "interrupt": interrupt})
        )

    async def step(self, iid: str, run_id: str | None, seq: int, doc: dict[str, Any]) -> None:
        await self._append(self._row(iid, run_id, "step", seq, doc))


# ------------------------------------------------------------------ assembly


def _ts(v: Any) -> str:
    return iso(v) if isinstance(v, datetime) else str(v)


def assemble_trace(incident_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold append-only rows into the agent_trace contract document."""
    runs: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in rows:
        rid = r["run_id"]
        if rid not in runs:
            runs[rid] = {
                "run_id": rid,
                "started_at": _ts(r["at"]),
                "finished_at": None,
                "status": "running",
                "steps": {},
                "interrupt": None,
                "_decision": None,
            }
            order.append(rid)
        run = runs[rid]
        doc = r["doc"]
        if r["kind"] == "run":
            if doc["phase"] == "start":
                run["started_at"] = _ts(r["at"])
                run["_decision"] = doc.get("decision")
            else:
                run["finished_at"] = _ts(r["at"])
                run["status"] = doc["status"]
                run["interrupt"] = doc.get("interrupt")
        else:
            run["steps"][int(r["seq"])] = dict(doc, seq=int(r["seq"]))
    out_runs: list[dict[str, Any]] = []
    for idx, rid in enumerate(order):
        run = runs[rid]
        later = idx < len(order) - 1
        if run["finished_at"] is None and later:  # process died mid-run; a resume run followed
            run["status"] = "failed"
        steps = [run["steps"][k] for k in sorted(run["steps"])]
        for s in steps:
            if s["status"] == "running" and run["status"] != "running":
                s["status"] = "failed"
                s["error_code"] = s["error_code"] or "process_restart"
        run["steps"] = steps
        out_runs.append(run)
    # attach decisions: a later run started by approve/reject closes the interrupt of the earlier run
    for idx, run in enumerate(out_runs):
        it = run["interrupt"]
        if it is None:
            continue
        it.setdefault("decision", None)
        it.setdefault("decided_by", None)
        for nxt in order[idx + 1 :]:
            d = runs[nxt]["_decision"]
            if d and d.get("action_id") == it["action_id"]:
                it["decision"] = "approved" if d["decision"] == "approve" else "rejected"
                it["decided_by"] = d.get("operator")
                break
    for run in out_runs:
        run.pop("_decision", None)
    return {"incident_id": incident_id, "thread_id": incident_id, "runs": out_runs}
