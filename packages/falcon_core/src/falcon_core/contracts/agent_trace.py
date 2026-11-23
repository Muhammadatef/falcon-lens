"""AgentTrace model: mirrors contracts/agent_trace.schema.json (closed schema: every object forbids extras)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Status = Literal["running", "interrupted", "completed", "failed"]
Node = Literal["enrich", "compare", "assess", "summarise", "propose", "act"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TraceTool(_Closed):
    name: str
    mode: Literal["read", "internal_auto", "external_draft"]
    status: Literal["ok", "error"]
    evidence_ids: Annotated[list[str], Field(max_length=20)]
    duration_ms: Annotated[int, Field(ge=0)]
    origin: Literal["model", "rule_fallback"] | None = None


class TraceLlm(_Closed):
    route: Literal["cloud", "local", "none"]
    model: str
    tokens_in: Annotated[int, Field(ge=0)]
    tokens_out: Annotated[int, Field(ge=0)]
    cost_usd: Annotated[float, Field(ge=0)]
    repaired: bool
    fallback_template: bool


class TraceBudget(_Closed):
    steps_used: Annotated[int, Field(ge=0)]
    tokens_used: Annotated[int, Field(ge=0)]
    elapsed_ms: Annotated[int, Field(ge=0)]


class TraceStep(_Closed):
    seq: Annotated[int, Field(ge=1)]
    node: Node
    started_at: str
    duration_ms: Annotated[int, Field(ge=0)]
    status: Status
    summary_en: Annotated[str, StringConstraints(max_length=300)]
    summary_ar: Annotated[str, StringConstraints(max_length=300)]
    tools: list[TraceTool]
    llm: TraceLlm | None
    generated_by: Literal["llm", "template", "rule"] | None = None
    budget: TraceBudget
    error_code: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,40}$")] | None


class TraceInterrupt(_Closed):
    action_id: str
    tool: str
    waiting_since: str
    pending_count: Annotated[int, Field(ge=1)] | None = None
    decision: Literal["approved", "rejected"] | None = None
    decided_by: str | None = None


class TraceRun(_Closed):
    run_id: str
    started_at: str
    finished_at: str | None
    status: Status
    steps: list[TraceStep]
    interrupt: TraceInterrupt | None


class AgentTrace(_Closed):
    incident_id: Annotated[str, StringConstraints(pattern=r"^inc_[0-9A-HJKMNP-TV-Z]{26}$")]
    thread_id: str
    runs: list[TraceRun]
