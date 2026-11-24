import { couldNotCheck, isHttpUrl, resultFromVerdict, type BatchResult } from "@/lib/batch";
import { WindowLimiter, visitorKey } from "@/lib/public-campaigns";
import { apiBase } from "../../public/campaigns/shared";

export const dynamic = "force-dynamic";

/** Per visitor IP: 240 URL checks a minute (a 500-URL batch at 3 in flight stays well under it). */
const limiter = new WindowLimiter(240, 60_000);
const MAX_URL = 2048;
const FINAL_TIMEOUT_MS = 45_000;
const noStore = { "Cache-Control": "no-store" };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Operator batch: checks ONE URL through POST /v1/check/url and returns a small result (the page loops over the file
 * and builds the CSV). The key the operator typed is forwarded to the API, which enforces its scope; this route holds
 * no key of its own and never submits on behalf of an unauthenticated visitor. Nothing is stored or logged here.
 */
export async function POST(request: Request): Promise<Response> {
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return Response.json({ error: "rate_limited" }, { status: 429, headers: { ...noStore, "Retry-After": String(wait) } });
  const key = (request.headers.get("x-ops-key") ?? "").trim();
  if (!key || key.length > 256) return Response.json({ error: "unauthorized" }, { status: 401, headers: noStore });

  let url: unknown;
  try {
    url = ((await request.json()) as { url?: unknown }).url;
  } catch {
    return Response.json({ error: "invalid_request" }, { status: 400, headers: noStore });
  }
  if (typeof url !== "string" || !url.trim() || url.length > MAX_URL) return Response.json({ error: "invalid_request" }, { status: 400, headers: noStore });

  if (!isHttpUrl(url)) return Response.json({ error: "not_http_url" }, { status: 400, headers: noStore });
  const headers = new Headers({ accept: "application/json", "content-type": "application/json", "x-api-key": key, "x-falcon-client-ip": visitorKey(request) });
  const t0 = Date.now();
  const respond = (r: BatchResult) => Response.json(r, { headers: noStore });
  try {
    const sub = await fetch(`${apiBase()}/v1/check/url?wait=8`, { method: "POST", headers, body: JSON.stringify({ url: url.trim() }), cache: "no-store", signal: AbortSignal.timeout(15_000) });
    if (sub.status === 401 || sub.status === 403) return Response.json({ error: sub.status === 403 ? "forbidden" : "unauthorized" }, { status: sub.status, headers: noStore });
    if (sub.status === 429) return Response.json({ error: "rate_limited" }, { status: 429, headers: { ...noStore, "Retry-After": sub.headers.get("retry-after") ?? "10" } });
    if (sub.status !== 200 && sub.status !== 202) return respond(couldNotCheck(`submit HTTP ${sub.status}`, Date.now() - t0));
    let doc = (await sub.json()) as { final?: boolean; verdict_id?: string };
    while (!doc.final) {
      if (!doc.verdict_id || Date.now() - t0 > FINAL_TIMEOUT_MS) return respond(couldNotCheck("no final verdict in time", Date.now() - t0, doc.verdict_id ?? ""));
      await sleep(600);
      const g = await fetch(`${apiBase()}/v1/verdicts/${encodeURIComponent(doc.verdict_id)}`, { headers, cache: "no-store", signal: AbortSignal.timeout(10_000) });
      if (g.status === 429) await sleep(2000);
      else if (g.status === 200) doc = (await g.json()) as typeof doc;
      else if (g.status !== 202 && g.status !== 404) return respond(couldNotCheck(`poll HTTP ${g.status}`, Date.now() - t0, doc.verdict_id));
    }
    return respond(resultFromVerdict(doc, Date.now() - t0));
  } catch {
    return respond(couldNotCheck("network error", Date.now() - t0));
  }
}
