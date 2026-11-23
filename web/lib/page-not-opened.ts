/**
 * A degraded verdict can mean "a source did not answer" or "we could not open the page itself". The second must
 * not read as if risk was found. UI-only classification of `degraded_reasons` (contract unchanged); the reason
 * strings come from the worker: `not_rendered:<why>`, `sandbox_unavailable:<why>`, `sandbox_timeout`, `dns_failure`,
 * `partial_render`, `static_fallback`.
 *
 * Two different messages: "dns" = no website answers at this address (the name does not resolve), "slow" = the
 * site exists but the page did not load (in time, or fully).
 */
const DNS = /^(dns_failure|(not_rendered|sandbox_unavailable):dns_failure)$/;
const SLOW =
  /^(not_rendered(:.*)?|sandbox_timeout|sandbox_unreachable|partial_render|static_fallback|sandbox_unavailable:(timeout|tls_error|http_403_empty|empty_response))$/;

export type NotOpenedKind = "dns" | "slow";

const isDns = (r: string): boolean => DNS.test(r);
const isSlow = (r: string): boolean => SLOW.test(r) && !isDns(r);

export function pageNotOpened(reasons: readonly string[] | null | undefined): boolean {
  return (reasons ?? []).some((r) => isDns(r) || isSlow(r));
}

/** Which message to show. DNS only when it is the whole story: any "page did not load" reason means the site exists. */
export function notOpenedKind(reasons: readonly string[] | null | undefined): NotOpenedKind {
  return (reasons ?? []).some(isSlow) ? "slow" : "dns";
}

/** True when every degraded reason is a page-not-opened one (then the generic "not every check completed" note adds nothing). */
export function onlyPageNotOpened(reasons: readonly string[] | null | undefined): boolean {
  const list = reasons ?? [];
  return list.length > 0 && list.every((r) => isDns(r) || isSlow(r));
}
