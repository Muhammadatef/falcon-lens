import { authHeaders } from "./api";

/** One authenticated GET (incident, trace). 404 is "not found", other failures are "not connected": never fake data. */
export type OneLoad<T> = { state: "ok"; value: T } | { state: "not_found" } | { state: "not_connected" } | { state: "unauthorized" };

export async function loadOne<T>(path: string, parse: (raw: unknown) => T | null, key?: string, signal?: AbortSignal): Promise<OneLoad<T>> {
  let response: Response;
  try {
    response = await fetch(path, { headers: authHeaders(key), credentials: "same-origin", cache: "no-store", signal });
  } catch {
    return { state: "not_connected" };
  }
  if (response.status === 401 || response.status === 403) return { state: "unauthorized" };
  if (response.status === 404) return { state: "not_found" };
  if (!response.ok || !(response.headers.get("content-type") ?? "").includes("json")) return { state: "not_connected" };
  try {
    const value = parse(await response.json());
    return value === null ? { state: "not_connected" } : { state: "ok", value };
  } catch {
    return { state: "not_connected" };
  }
}
