/**
 * Browser client for the Falcon Lens REST v1 API (same origin, behind the gateway).
 * Aligned with services/api (PR #4) and contracts/openapi.yaml:
 *  - url/message are JSON; email and image are multipart with one field named `file`
 *    (email must be an RFC 5322 `.eml`; image must be PNG, JPEG or WebP);
 *  - 202 carries {verdict_id, events_url, status_url}; 200 (cache hit) carries the final Verdict;
 *  - GET /v1/verdicts/{id} answers 200 final, 202 partial, 404 unknown or nothing published yet;
 *  - limits are in bytes: URL 4 KB, message 8 KB UTF-8, email 2 MB, image 5 MB.
 * Errors are RFC 9457 problem+json; they are mapped to a small `Problem` the UI can
 * translate. Nothing here ever fabricates a result: a failed call is a failed call.
 */
import { VERDICT_ID_RE, parseVerdict, type Verdict } from "./contracts";
import type { Problem } from "./verdict-stream";

export const LIMITS = { urlBytes: 4096, messageBytes: 8 * 1024, emailBytes: 2 * 1024 * 1024, imageBytes: 5 * 1024 * 1024 } as const;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"] as const;

export const utf8Bytes = (text: string): number => new TextEncoder().encode(text).length;

/** Mirrors the API's `looks_like_eml`: a header line first, and at least one well-known header. */
export function looksLikeEml(text: string): boolean {
  const head = text.slice(0, 16384);
  return !head.includes("\u0000") && /^(From [^\r\n]*|[!-9;-~]{1,64}:[^\r\n]*)\r?\n/.test(head) && /^(from|to|subject|received|date|message-id|mime-version):/im.test(head);
}

/** Pasted raw email → the `.eml` upload the API expects. */
export const emlFile = (raw: string): File => new File([raw], "pasted.eml", { type: "message/rfc822" });

export type CheckInput =
  | { kind: "url"; url: string }
  | { kind: "message"; text: string }
  | { kind: "email"; file: File }
  | { kind: "image"; file: File };

export interface Accepted {
  verdictId: string;
  eventsUrl: string;
  /** Present when the API answered with a complete verdict instead of 202. */
  verdict?: Verdict;
}

export class ApiError extends Error {
  constructor(public readonly problem: Problem) {
    super(`api ${problem.kind} ${problem.status}`);
  }
}

export function problemFromStatus(status: number, retryAfterHeader?: string | null): Problem {
  const retry = retryAfterHeader ? Number.parseInt(retryAfterHeader, 10) : NaN;
  const retryAfter = Number.isFinite(retry) && retry > 0 ? Math.min(retry, 3600) : undefined;
  if (status === 429) return { kind: "rate_limited", status, retryAfter };
  if (status === 413) return { kind: "too_large", status };
  if (status === 404) return { kind: "not_found", status };
  if (status === 415) return { kind: "unsupported", status };
  if (status === 400 || status === 411 || status === 422) return { kind: "invalid", status };
  return { kind: "unavailable", status };
}

/** Only same-origin API paths are ever opened; anything else falls back to the canonical path. */
export function safeEventsUrl(candidate: unknown, verdictId: string): string {
  const fallback = `/v1/verdicts/${verdictId}/events`;
  if (typeof candidate !== "string") return fallback;
  return /^\/v1\/verdicts\/[A-Za-z0-9_]+\/events(\?[A-Za-z0-9_=&.-]*)?$/.test(candidate) ? candidate : fallback;
}

async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(path, { ...init, credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new ApiError({ kind: "network", status: 0 });
  }
  if (!response.ok) throw new ApiError(problemFromStatus(response.status, response.headers.get("retry-after")));
  return response;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "content-type": "application/json", accept: "application/json" },
  body: JSON.stringify(body),
});

const multipart = (file: File): RequestInit => {
  const form = new FormData();
  form.append("file", file, file.name);
  return { method: "POST", headers: { accept: "application/json" }, body: form };
};

export async function submitCheck(input: CheckInput): Promise<Accepted> {
  let response: Response;
  if (input.kind === "url") response = await request("/v1/check/url", json({ url: input.url }));
  else if (input.kind === "message") response = await request("/v1/check/message", json({ text: input.text }));
  else if (input.kind === "image") response = await request("/v1/check/image", multipart(input.file));
  else response = await request("/v1/check/email", multipart(input.file));

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError({ kind: "unavailable", status: response.status });
  }
  const id = (body as { verdict_id?: unknown } | null)?.verdict_id;
  if (typeof id !== "string" || !VERDICT_ID_RE.test(id)) throw new ApiError({ kind: "unavailable", status: response.status });
  const verdict = parseVerdict(body) ?? undefined;
  return { verdictId: id, eventsUrl: safeEventsUrl((body as { events_url?: unknown }).events_url, id), verdict };
}

export async function fetchVerdict(verdictId: string, signal?: AbortSignal): Promise<Verdict | null> {
  if (!VERDICT_ID_RE.test(verdictId)) throw new ApiError({ kind: "not_found", status: 404 });
  const response = await request(`/v1/verdicts/${verdictId}`, { method: "GET", headers: { accept: "application/json" }, signal });
  try {
    return parseVerdict(await response.json());
  } catch {
    return null;
  }
}

/* ── Boards ───────────────────────────────────────────────────────────── */

export type BoardLoad<T> = { state: "ok"; items: T[] } | { state: "not_connected"; status: number } | { state: "unauthorized" };

/**
 * Loads a board list. A 404 / 5xx / network failure means the endpoint is not there
 * yet: the caller shows "not connected", never placeholder data.
 */
export async function loadBoard<T>(path: string, parse: (raw: unknown) => T | null, unwrap: (raw: unknown) => unknown[], key?: string, signal?: AbortSignal): Promise<BoardLoad<T>> {
  let response: Response;
  try {
    response = await fetch(path, { headers: authHeaders(key), credentials: "same-origin", cache: "no-store", signal });
  } catch {
    return { state: "not_connected", status: 0 };
  }
  if (response.status === 401 || response.status === 403) return { state: "unauthorized" };
  if (!response.ok) return { state: "not_connected", status: response.status };
  if (!(response.headers.get("content-type") ?? "").includes("json")) return { state: "not_connected", status: response.status };
  try {
    const items = unwrap(await response.json()).map(parse).filter((x): x is T => x !== null);
    return { state: "ok", items };
  } catch {
    return { state: "not_connected", status: response.status };
  }
}

export function authHeaders(key?: string): Record<string, string> {
  const headers: Record<string, string> = { accept: "application/json" };
  if (key) headers.authorization = `Bearer ${key}`;
  return headers;
}

/** Operator decision on a Sentinel-proposed external action. Path is an assumption logged in DECISIONS.md. */
export async function decideAction(incidentId: string, actionId: string, decision: "approve" | "reject", key: string): Promise<Problem | null> {
  const path = `/v1/incidents/${encodeURIComponent(incidentId)}/actions/${encodeURIComponent(actionId)}/${decision}`;
  try {
    const response = await fetch(path, { method: "POST", headers: authHeaders(key), credentials: "same-origin", cache: "no-store" });
    return response.ok ? null : problemFromStatus(response.status, response.headers.get("retry-after"));
  } catch {
    return { kind: "network", status: 0 };
  }
}

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
