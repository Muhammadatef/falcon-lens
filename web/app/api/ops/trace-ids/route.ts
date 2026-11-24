import { VERDICT_ID_RE } from "@/lib/contracts";
import { opsKey, operatorHeaders, requireOperator } from "@/lib/ops-gate";
import { TRACE_ID_RE } from "@/lib/observability";
import { apiBase } from "../../public/campaigns/shared";

export const dynamic = "force-dynamic";
const MAX_IDS = 100;
const noStore = { "Cache-Control": "no-store" };

/**
 * Operator only: `?verdicts=vd_a,vd_b` -> `{ trace_ids: { vd_a: "<32 hex>" } }`. The typed key is forwarded to the API,
 * which enforces its scope (see `requireOperator`); only ids that are 32 lowercase hex are returned, nothing else from the verdict.
 */
export async function GET(request: Request): Promise<Response> {
  const refused = await requireOperator(request);
  if (refused) return refused;
  const key = opsKey(request)!;
  const ids = [...new Set((new URL(request.url).searchParams.get("verdicts") ?? "").split(",").map((s) => s.trim()).filter(Boolean))];
  if (ids.length === 0 || ids.length > MAX_IDS || !ids.every((id) => VERDICT_ID_RE.test(id))) return Response.json({ error: "invalid_request" }, { status: 400, headers: noStore });
  const out: Record<string, string> = {};
  await Promise.all(
    ids.map(async (id) => {
      try {
        const r = await fetch(`${apiBase()}/v1/verdicts/${id}`, { headers: operatorHeaders(request, key), cache: "no-store", signal: AbortSignal.timeout(8_000) });
        if (!r.ok) return;
        const doc = (await r.json()) as { trace_id?: unknown };
        if (typeof doc.trace_id === "string" && TRACE_ID_RE.test(doc.trace_id)) out[id] = doc.trace_id;
      } catch {
        /* no trace id for this one */
      }
    }),
  );
  return Response.json({ trace_ids: out }, { headers: noStore });
}
