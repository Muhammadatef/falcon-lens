import { toPublicHunt } from "@/lib/hunt";
import { WindowLimiter, visitorKey } from "@/lib/public-campaigns";
import { apiBase, notConnected, upstreamHeaders } from "../campaigns/shared";

export const dynamic = "force-dynamic";

const limiter = new WindowLimiter(30, 60_000);

/** Public, read-only hunting feed: server-side call with the read key; only arbiter-confirmed, defanged rows pass. */
export async function GET(request: Request) {
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });
  const headers = upstreamHeaders(request, "application/json");
  if (!headers) return notConnected(503);
  try {
    const opts = { headers, cache: "no-store" as const, signal: AbortSignal.timeout(8_000) };
    const [feedRes, metaRes] = await Promise.all([
      fetch(`${apiBase()}/v1/hunt/candidates?limit=50`, opts),
      fetch(`${apiBase()}/v1/meta`, opts).catch(() => null),
    ]);
    if (!feedRes.ok) return notConnected(feedRes.status === 404 ? 404 : 502);
    const feed: unknown = await feedRes.json();
    const meta: unknown = metaRes && metaRes.ok ? await metaRes.json().catch(() => null) : null;
    return Response.json(toPublicHunt(feed, meta), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return notConnected(502);
  }
}
