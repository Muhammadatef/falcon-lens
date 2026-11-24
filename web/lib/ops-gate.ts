import { apiBase } from "@/app/api/public/campaigns/shared";

const noStore = { "Cache-Control": "no-store" };
const OK_TTL_MS = 30_000;
const verified = new Map<string, number>();

export const MAX_KEY = 256;

/** The operator key the browser sent (`x-ops-key`), or null. */
export const opsKey = (request: Request): string | null => {
  const key = (request.headers.get("x-ops-key") ?? "").trim();
  return key && key.length <= MAX_KEY ? key : null;
};

/**
 * Operator gate for `/api/ops/*`: the key is checked against the API (operator scope, GET /v1/admin/llm-route:
 * 401 unknown key, 403 key without operator scope). This web server holds no key of its own for it, so an anonymous
 * visitor can never get anything through here. Returns a Response to send (the refusal) or null when the key is an operator key.
 */
export async function requireOperator(request: Request): Promise<Response | null> {
  const key = opsKey(request);
  if (!key) return Response.json({ error: "unauthorized" }, { status: 401, headers: noStore });
  const at = process.env.FL_WEB_TEST_FORWARD_COOKIE ? undefined : verified.get(key);
  if (at !== undefined && Date.now() - at < OK_TTL_MS) return null;
  try {
    const r = await fetch(`${apiBase()}/v1/admin/llm-route`, { headers: operatorHeaders(request, key), cache: "no-store", signal: AbortSignal.timeout(8_000) });
    if (r.status === 401 || r.status === 403) return Response.json({ error: r.status === 403 ? "forbidden" : "unauthorized" }, { status: r.status, headers: noStore });
    if (!r.ok) return Response.json({ error: "not_connected" }, { status: 502, headers: noStore });
  } catch {
    return Response.json({ error: "not_connected" }, { status: 502, headers: noStore });
  }
  if (verified.size > 64) verified.clear();
  verified.set(key, Date.now());
  return null;
}

/** Headers for an upstream call made with the operator's own key. Test-only: forwards the mock-board cookie when FL_WEB_TEST_FORWARD_COOKIE is set (same switch as the public routes). */
export function operatorHeaders(request: Request, key: string): Headers {
  const h = new Headers({ accept: "application/json", "x-api-key": key });
  const name = (process.env.FL_WEB_TEST_FORWARD_COOKIE ?? "").replace(/[^\w-]/g, "");
  const match = name ? new RegExp(`(?:^|;\\s*)${name}=([^;]+)`).exec(request.headers.get("cookie") ?? "") : null;
  if (match) h.set("cookie", `${name}=${match[1]}`);
  return h;
}

export const resetOperatorCache = () => verified.clear();
