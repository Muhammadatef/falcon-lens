import { authHeaders } from "./api";

/** Language-model route (GET/PUT /v1/admin/llm-route, operator scope; read-only copy in GET /v1/meta). */
export type RouteMode = "cloud_with_local_fallback" | "local" | "cloud_only" | "auto";
export type EffectiveMode = "cloud_with_local_fallback" | "local" | "cloud_only";

export type LlmRoute = {
  mode: RouteMode;
  effective_mode: EffectiveMode;
  local_model: string;
  local_models: string[];
  modes: RouteMode[];
  cloud_available: boolean;
  sovereign_locked: boolean;
  source: "runtime" | "environment";
  updated_at: string | null;
  updated_by: string | null;
};

const MODES: readonly string[] = ["cloud_with_local_fallback", "local", "cloud_only", "auto"];
const EFFECTIVE: readonly string[] = ["cloud_with_local_fallback", "local", "cloud_only"];
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

/** Strict parse: anything unexpected is rejected, nothing is rendered as HTML. */
export function parseLlmRoute(raw: unknown): LlmRoute | null {
  if (typeof raw !== "object" || raw === null) return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.mode !== "string" || !MODES.includes(r.mode)) return null;
  if (typeof r.effective_mode !== "string" || !EFFECTIVE.includes(r.effective_mode)) return null;
  const local = str(r.local_model);
  if (!local || !Array.isArray(r.local_models)) return null;
  return {
    mode: r.mode as RouteMode,
    effective_mode: r.effective_mode as EffectiveMode,
    local_model: local,
    local_models: r.local_models.filter((m): m is string => typeof m === "string"),
    modes: MODES as RouteMode[],
    cloud_available: r.cloud_available === true,
    sovereign_locked: r.sovereign_locked === true,
    source: r.source === "runtime" ? "runtime" : "environment",
    updated_at: str(r.updated_at),
    updated_by: str(r.updated_by),
  };
}

const URL_PATH = "/v1/admin/llm-route";

export async function getLlmRoute(key: string, signal?: AbortSignal): Promise<{ status: number; route: LlmRoute | null }> {
  try {
    const res = await fetch(URL_PATH, { headers: authHeaders(key), credentials: "same-origin", cache: "no-store", signal });
    return { status: res.status, route: res.ok ? parseLlmRoute(await res.json()) : null };
  } catch {
    return { status: 0, route: null };
  }
}

export async function putLlmRoute(key: string, mode: RouteMode, localModel: string | null): Promise<{ status: number; route: LlmRoute | null }> {
  try {
    const res = await fetch(URL_PATH, {
      method: "PUT",
      headers: { ...authHeaders(key), "content-type": "application/json" },
      body: JSON.stringify({ mode, local_model: localModel }),
      credentials: "same-origin",
      cache: "no-store",
    });
    return { status: res.status, route: res.ok ? parseLlmRoute(await res.json()) : null };
  } catch {
    return { status: 0, route: null };
  }
}
