/**
 * A degraded verdict can mean "a source did not answer" or "we could not open the page itself". The second must
 * not read as if risk was found. UI-only classification of `degraded_reasons` (contract unchanged); the reason
 * strings come from the worker: `not_rendered:<why>`, `sandbox_timeout`, `dns_failure`.
 */
const NOT_OPENED = /^(not_rendered(:.*)?|sandbox_timeout|dns_failure|sandbox_unreachable)$/;

export function pageNotOpened(reasons: readonly string[] | null | undefined): boolean {
  return (reasons ?? []).some((r) => NOT_OPENED.test(r));
}

/** True when every degraded reason is a page-not-opened one (then the generic "not every check completed" note adds nothing). */
export function onlyPageNotOpened(reasons: readonly string[] | null | undefined): boolean {
  const list = reasons ?? [];
  return list.length > 0 && list.every((r) => NOT_OPENED.test(r));
}
