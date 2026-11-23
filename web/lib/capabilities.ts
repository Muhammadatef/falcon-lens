import bundled from "./capabilities.generated.json";

/**
 * One source for every "Live / In progress" badge (server side only). Order of truth:
 *   1. `capabilities` in GET /v1/meta, if the API provides it (booleans by id), else
 *   2. lib/capabilities.generated.json, written at build by scripts/sync-results.mjs from the
 *      repo's own probes (scripts/submission/capabilities.py).
 * A missing flag counts as "in progress", never as live.
 */
export type CapId =
  | "message_check"
  | "email_check"
  | "image_check"
  | "injection_defence"
  | "investigator"
  | "sentinel_agent"
  | "rest_api"
  | "mcp"
  | "stix"
  | "t1_measured_model";
export type Capabilities = Record<CapId, boolean>;

export const CAP_IDS: readonly CapId[] = ["message_check", "email_check", "image_check", "injection_defence", "investigator", "sentinel_agent", "rest_api", "mcp", "stix", "t1_measured_model"];
const API_BASE = (process.env.FL_API_INTERNAL_URL ?? "http://api:8000").replace(/\/+$/, "");

export function mergeCapabilities(base: unknown, runtime: unknown): Capabilities {
  const out = {} as Capabilities;
  for (const id of CAP_IDS) {
    const r = (runtime as Record<string, unknown> | null)?.[id];
    const b = (base as Record<string, unknown> | null)?.[id];
    out[id] = typeof r === "boolean" ? r : b === true;
  }
  return out;
}

export async function loadCapabilities(): Promise<Capabilities> {
  let runtime: unknown = null;
  try {
    const response = await fetch(`${API_BASE}/v1/meta`, { cache: "no-store", signal: AbortSignal.timeout(1500) });
    if (response.ok) runtime = ((await response.json()) as { capabilities?: unknown }).capabilities ?? null;
  } catch {
    runtime = null;
  }
  return mergeCapabilities(bundled, runtime);
}
