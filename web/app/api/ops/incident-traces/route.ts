import { INCIDENT_ID_RE } from "@/lib/contracts";
import { opsKey, operatorHeaders, requireOperator } from "@/lib/ops-gate";
import { TRACE_ID_RE } from "@/lib/observability";
import { apiBase } from "../../public/campaigns/shared";

export const dynamic = "force-dynamic";
const MAX_IDS = 20;
const noStore = { "Cache-Control": "no-store" };

export interface IncidentTraceLink {
  /** Trace id of the latest agent run that has one. */
  trace_id?: string;
  /** Epoch ms span of all runs, for the Grafana time range. */
  from?: number;
  to?: number;
}

/**
 * Operator only: `?incidents=inc_a` -> `{ traces: { inc_a: { trace_id, from, to } } }` from the agent trace. The typed key is
 * forwarded to the API (scope enforced there, see `requireOperator`); only a validated trace id and two timestamps are returned.
 */
export async function GET(request: Request): Promise<Response> {
  const refused = await requireOperator(request);
  if (refused) return refused;
  const key = opsKey(request)!;
  const ids = [...new Set((new URL(request.url).searchParams.get("incidents") ?? "").split(",").map((s) => s.trim()).filter(Boolean))];
  if (ids.length === 0 || ids.length > MAX_IDS || !ids.every((id) => INCIDENT_ID_RE.test(id))) return Response.json({ error: "invalid_request" }, { status: 400, headers: noStore });
  const out: Record<string, IncidentTraceLink> = {};
  await Promise.all(
    ids.map(async (id) => {
      try {
        const r = await fetch(`${apiBase()}/v1/incidents/${id}/trace`, { headers: operatorHeaders(request, key), cache: "no-store", signal: AbortSignal.timeout(8_000) });
        if (!r.ok) return;
        const doc = (await r.json()) as { runs?: { trace_id?: unknown; started_at?: unknown; finished_at?: unknown }[] };
        const runs = Array.isArray(doc.runs) ? doc.runs.slice(0, 50) : [];
        const times = runs.flatMap((x) => [x.started_at, x.finished_at]).map((t) => (typeof t === "string" ? Date.parse(t) : NaN)).filter(Number.isFinite);
        const withTrace = [...runs].reverse().find((x) => typeof x.trace_id === "string" && TRACE_ID_RE.test(x.trace_id));
        out[id] = {
          ...(withTrace ? { trace_id: withTrace.trace_id as string } : {}),
          ...(times.length ? { from: Math.min(...times), to: Math.max(...times) } : {}),
        };
      } catch {
        /* nothing for this one */
      }
    }),
  );
  return Response.json({ traces: out }, { headers: noStore });
}
