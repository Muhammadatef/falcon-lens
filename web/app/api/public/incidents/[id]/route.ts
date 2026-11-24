import { WindowLimiter, visitorKey } from "@/lib/public-campaigns";
import { toPublicIncident, toPublicTrace } from "@/lib/public-history";
import { apiBase, notConnected, upstreamHeaders } from "../../campaigns/shared";

export const dynamic = "force-dynamic";
const limiter = new WindowLimiter(60, 60_000);

/** Public, read-only incident: header fields and the node timeline (names, timestamps, tool names). No drafts, no approve/reject. */
export async function GET(request: Request, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!/^inc_[0-9A-HJKMNP-TV-Z]{26}$/.test(id)) return notConnected(404);
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });
  const headers = upstreamHeaders(request, "application/json");
  if (!headers) return notConnected(503);
  try {
    const get = (p: string) => fetch(`${apiBase()}${p}`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) });
    const [inc, tr] = await Promise.all([get(`/v1/incidents/${id}`), get(`/v1/incidents/${id}/trace`)]);
    if (inc.status === 404 || tr.status === 404) return notConnected(404);
    if (inc.status === 429 || tr.status === 429) return notConnected(429, { "Retry-After": "10" });
    if (!inc.ok || !tr.ok) return notConnected(502);
    const incident = toPublicIncident(await inc.json());
    const trace = toPublicTrace(await tr.json());
    if (!incident || !trace) return notConnected(502);
    return Response.json({ incident, trace }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return notConnected(502);
  }
}
