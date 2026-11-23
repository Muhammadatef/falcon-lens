/**
 * Sentinel agent run trace (contracts/agent_trace.schema.json). Everything arrives through
 * `parseAgentTrace`, so a malformed or hostile payload can never put a non-string, an unknown
 * enum or a negative number into the tree. All strings are rendered as text by the components.
 */
import { INCIDENT_ID_RE } from "./contracts";

export const NODES = ["enrich", "compare", "assess", "summarise", "propose", "act"] as const;
export type NodeName = (typeof NODES)[number];
export type RunStatus = "running" | "interrupted" | "completed" | "failed";
export type ToolMode = "read" | "internal_auto" | "external_draft";
export type LlmRoute = "cloud" | "local" | "none";

export interface TraceTool {
  name: string;
  mode: ToolMode;
  status: "ok" | "error";
  evidence_ids: string[];
  duration_ms: number;
}
export interface TraceLlm {
  route: LlmRoute;
  model: string;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  repaired: boolean;
  fallback_template: boolean;
}
export interface TraceStep {
  seq: number;
  node: NodeName;
  started_at: string;
  duration_ms: number;
  status: RunStatus;
  summary_en: string;
  summary_ar: string;
  tools: TraceTool[];
  llm: TraceLlm | null;
  budget: { steps_used: number; tokens_used: number; elapsed_ms: number };
  error_code: string | null;
}
export interface TraceInterrupt {
  action_id: string;
  tool: string;
  waiting_since: string;
  pending_count?: number;
  decision?: "approved" | "rejected" | null;
  decided_by?: string | null;
}
export interface TraceRun {
  run_id: string;
  started_at: string;
  finished_at: string | null;
  status: RunStatus;
  steps: TraceStep[];
  interrupt: TraceInterrupt | null;
}
export interface AgentTrace {
  incident_id: string;
  thread_id: string;
  runs: TraceRun[];
}

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const nat = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0);
const oneOf = <T extends string>(v: unknown, allowed: readonly T[]): T | null => (typeof v === "string" && (allowed as readonly string[]).includes(v) ? (v as T) : null);
const STATUSES = ["running", "interrupted", "completed", "failed"] as const;

function parseTool(raw: unknown): TraceTool | null {
  if (!isObj(raw) || typeof raw.name !== "string") return null;
  const mode = oneOf(raw.mode, ["read", "internal_auto", "external_draft"] as const);
  if (!mode) return null;
  return {
    name: raw.name,
    mode,
    status: raw.status === "error" ? "error" : "ok",
    evidence_ids: Array.isArray(raw.evidence_ids) ? raw.evidence_ids.filter((x): x is string => typeof x === "string").slice(0, 20) : [],
    duration_ms: nat(raw.duration_ms),
  };
}

function parseLlm(raw: unknown): TraceLlm | null {
  if (!isObj(raw)) return null;
  const route = oneOf(raw.route, ["cloud", "local", "none"] as const);
  if (!route) return null;
  return { route, model: str(raw.model), tokens_in: nat(raw.tokens_in), tokens_out: nat(raw.tokens_out), cost_usd: nat(raw.cost_usd), repaired: raw.repaired === true, fallback_template: raw.fallback_template === true };
}

function parseStep(raw: unknown): TraceStep | null {
  if (!isObj(raw)) return null;
  const node = oneOf(raw.node, NODES);
  const status = oneOf(raw.status, STATUSES);
  if (!node || !status || typeof raw.seq !== "number") return null;
  const b = isObj(raw.budget) ? raw.budget : {};
  return {
    seq: raw.seq,
    node,
    started_at: str(raw.started_at),
    duration_ms: nat(raw.duration_ms),
    status,
    summary_en: str(raw.summary_en),
    summary_ar: str(raw.summary_ar),
    tools: (Array.isArray(raw.tools) ? raw.tools : []).map(parseTool).filter((t): t is TraceTool => t !== null),
    llm: parseLlm(raw.llm),
    budget: { steps_used: nat(b.steps_used), tokens_used: nat(b.tokens_used), elapsed_ms: nat(b.elapsed_ms) },
    error_code: typeof raw.error_code === "string" ? raw.error_code : null,
  };
}

function parseInterrupt(raw: unknown): TraceInterrupt | null {
  if (!isObj(raw) || typeof raw.action_id !== "string") return null;
  return {
    action_id: raw.action_id,
    tool: str(raw.tool),
    waiting_since: str(raw.waiting_since),
    pending_count: typeof raw.pending_count === "number" ? raw.pending_count : undefined,
    decision: raw.decision === "approved" || raw.decision === "rejected" ? raw.decision : null,
    decided_by: typeof raw.decided_by === "string" ? raw.decided_by : null,
  };
}

export function parseAgentTrace(raw: unknown): AgentTrace | null {
  if (!isObj(raw) || typeof raw.incident_id !== "string" || !INCIDENT_ID_RE.test(raw.incident_id)) return null;
  const runs: TraceRun[] = [];
  for (const r of Array.isArray(raw.runs) ? raw.runs : []) {
    if (!isObj(r) || typeof r.run_id !== "string") continue;
    runs.push({
      run_id: r.run_id,
      started_at: str(r.started_at),
      finished_at: typeof r.finished_at === "string" ? r.finished_at : null,
      status: oneOf(r.status, STATUSES) ?? "running",
      steps: (Array.isArray(r.steps) ? r.steps : []).map(parseStep).filter((s): s is TraceStep => s !== null),
      interrupt: parseInterrupt(r.interrupt),
    });
  }
  return { incident_id: raw.incident_id, thread_id: str(raw.thread_id), runs };
}

/** The run that is still moving or waiting (the last one), or null once the trace is settled. */
export const liveRun = (trace: AgentTrace): TraceRun | null => {
  const last = trace.runs[trace.runs.length - 1];
  return last && (last.status === "running" || last.status === "interrupted") ? last : null;
};

/** Cards in display order: one per executed step, across runs, oldest first. */
export const flatSteps = (trace: AgentTrace): { run: TraceRun; step: TraceStep }[] =>
  trace.runs.flatMap((run) => run.steps.map((step) => ({ run, step }))).sort((a, b) => a.step.seq - b.step.seq);

/** Internal link to an incident's trace page. Only a well-formed incident id ever reaches an href. */
export const traceHref = (incidentId: string, demo: boolean): string =>
  INCIDENT_ID_RE.test(incidentId) ? `/incidents/${incidentId}${demo ? "?demo=1" : ""}` : "/ops";
