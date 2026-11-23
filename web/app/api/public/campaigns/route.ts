import { WindowLimiter, toPublicList, visitorKey } from "@/lib/public-campaigns";
import { apiBase, notConnected, upstreamHeaders } from "./shared";

export const dynamic = "force-dynamic";

const limiter = new WindowLimiter(30, 60_000);

/** Public, read-only campaign list: server-side call with the service key, allow-listed fields only. */
export async function GET(request: Request) {
  const wait = limiter.take(visitorKey(request));
  if (wait > 0) return notConnected(429, { "Retry-After": String(wait) });
  const headers = upstreamHeaders(request, "application/json");
  if (!headers) return notConnected(503);
  try {
    const upstream = await fetch(`${apiBase()}/v1/campaigns?limit=50`, { headers, cache: "no-store", signal: AbortSignal.timeout(8_000) });
    if (!upstream.ok) return notConnected(upstream.status === 404 ? 404 : 502);
    const body: unknown = await upstream.json();
    return Response.json({ items: toPublicList(body) }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return notConnected(502);
  }
}
