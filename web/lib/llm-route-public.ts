/** Server side: the active language-model route as GET /v1/meta reports it (read-only). null when unknown: nothing is shown then. */
export type PublicRoute = { mode: "cloud_with_local_fallback" | "local" | "cloud_only"; local_model: string; sovereign: boolean };

const API_BASE = (process.env.FL_API_INTERNAL_URL ?? "http://api:8000").replace(/\/+$/, "");
const MODES = ["cloud_with_local_fallback", "local", "cloud_only"];

export function parsePublicRoute(raw: unknown): PublicRoute | null {
  const r = (raw as { llm_route?: unknown } | null)?.llm_route as Record<string, unknown> | null | undefined;
  if (!r || typeof r.mode !== "string" || !MODES.includes(r.mode) || typeof r.local_model !== "string") return null;
  return { mode: r.mode as PublicRoute["mode"], local_model: r.local_model, sovereign: r.sovereign === true };
}

export async function loadPublicRoute(): Promise<PublicRoute | null> {
  try {
    const response = await fetch(`${API_BASE}/v1/meta`, { cache: "no-store", signal: AbortSignal.timeout(1500) });
    return response.ok ? parsePublicRoute(await response.json()) : null;
  } catch {
    return null;
  }
}
