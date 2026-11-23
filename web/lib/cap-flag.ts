import type { Capabilities } from "./capabilities";

/**
 * Reads one flag from `loadCapabilities()` by id. The id may be one that lib/capabilities.ts does not list yet
 * (e.g. `sentinel_agent`, `rest_api`, `mcp`, `stix` arrive with the capability-flag card); a missing flag counts
 * as "in progress", never as live.
 */
export function flag(caps: Capabilities, id: string): boolean {
  return (caps as unknown as Record<string, unknown>)[id] === true;
}
