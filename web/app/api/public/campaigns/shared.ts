import { visitorKey } from "@/lib/public-campaigns";

export const apiBase = () => (process.env.FL_API_INTERNAL_URL ?? "http://api:8000").replace(/\/+$/, "");

/** Headers for the upstream call. The key is read per call, sent only server to server, never logged or returned. */
export function upstreamHeaders(request: Request, accept: string): Headers | null {
  const key = process.env.FL_WEB_READ_KEY;
  if (!key) return null;
  const h = new Headers({ accept, "x-api-key": key, "x-falcon-client-ip": visitorKey(request) });
  // Test-only: lets the mock gateway pick a scenario. Off unless explicitly set; visitor cookies are never forwarded otherwise.
  const name = (process.env.FL_WEB_TEST_FORWARD_COOKIE ?? "").replace(/[^\w-]/g, "");
  const match = name ? new RegExp(`(?:^|;\\s*)${name}=([^;]+)`).exec(request.headers.get("cookie") ?? "") : null;
  if (match) h.set("cookie", `${name}=${match[1]}`);
  return h;
}

export const notConnected = (status = 502, extra: Record<string, string> = {}) =>
  Response.json({ error: "not_connected" }, { status, headers: { "Cache-Control": "no-store", ...extra } });
