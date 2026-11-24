import { authHeaders } from "./api";

/**
 * Hunt mode ("Hunting | الرصد الاستباقي", docs/design/HUNTER.md section 6).
 * Public feed: GET /v1/hunt/candidates (read key, server side) + the `hunt` block of GET /v1/meta.
 * Operator view: GET/PUT /v1/admin/hunt (operator key, from /ops).
 * Every parser is an allow-list: unknown fields are dropped, anything off-shape rejects the row, nothing is HTML.
 */

export type HuntSourceStatus = "live" | "ready_needs_key" | "disabled";
export type HuntSource = { id: string; kind: string; status: HuntSourceStatus };
export type HuntReason = "brand_token_in_cert" | "resolves_a" | "has_mx" | "cert_fresh" | "permutation:typo" | "permutation:homoglyph" | "permutation:combosquat" | "permutation:tld_swap";
export type HuntItem = {
  id: string;
  domain: string; // defanged, plain text only
  brandId: string;
  brandName: { ar: string; en: string } | null;
  reasons: HuntReason[];
  firstSeen: string;
  verdict: "suspicious" | "dangerous";
  foundBeforeReport: boolean;
  ttdSeconds: number | null;
  ttdBasis: "cert_not_before" | "rdap" | null;
  source: "live" | "fixture" | "replay";
};
export type HuntCounts = Partial<Record<HuntStatus, number>>;
export type HuntStatus = "new" | "unregistered" | "queued" | "submitted" | "confirmed" | "cleared" | "already_known" | "skipped_quota" | "error";
export type PublicHunt = { enabled: boolean | null; paused: boolean; sources: HuntSource[]; items: HuntItem[]; counts: HuntCounts };

const REASONS: readonly string[] = ["brand_token_in_cert", "resolves_a", "has_mx", "cert_fresh", "permutation:typo", "permutation:homoglyph", "permutation:combosquat", "permutation:tld_swap"];
const STATUSES: readonly string[] = ["new", "unregistered", "queued", "submitted", "confirmed", "cleared", "already_known", "skipped_quota", "error"];
const SOURCE_IDS: readonly string[] = ["permutation", "ct_lookup", "ct_search", "fixture", "search", "ads", "maps"];
const SOURCE_STATUS: readonly string[] = ["live", "ready_needs_key", "disabled"];
const DEFANGED = /^[^.\s<>"'`]+(\[\.\][^.\s<>"'`]+)+$/;
const CANDIDATE_ID = /^hc_[0-9A-HJKMNP-TV-Z]{26}$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

const obj = (v: unknown): Record<string, unknown> | null => (typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const clean = (s: string, max = 80): string => s.replace(/[\u0000-\u001f\u007f‪-‮⁦-⁩<>]/g, "").slice(0, max);

export function parseHuntItem(raw: unknown): HuntItem | null {
  const r = obj(raw);
  if (!r) return null;
  const id = str(r.candidate_id);
  const domain = str(r.domain_defanged);
  const brandId = str(r.brand_id);
  const firstSeen = str(r.first_seen);
  if (!id || !CANDIDATE_ID.test(id) || !domain || !DEFANGED.test(domain) || domain.length > 253 || !brandId || !firstSeen || !ISO.test(firstSeen)) return null;
  if (r.verdict !== "suspicious" && r.verdict !== "dangerous") return null; // only arbiter-confirmed rows are public
  if (!Array.isArray(r.reasons) || !r.reasons.every((x) => typeof x === "string" && REASONS.includes(x))) return null;
  const bn = obj(r.brand_name);
  const ar = bn ? str(bn.ar) : null;
  const en = bn ? str(bn.en) : null;
  const ttd = typeof r.time_to_detection_s === "number" && Number.isFinite(r.time_to_detection_s) && r.time_to_detection_s >= 0 ? r.time_to_detection_s : null;
  const basis = r.time_to_detection_basis === "cert_not_before" || r.time_to_detection_basis === "rdap" ? r.time_to_detection_basis : null;
  const source = r.source === "fixture" || r.source === "replay" ? r.source : r.source === "live" ? "live" : null;
  if (!source) return null;
  return {
    id,
    domain,
    brandId: clean(brandId, 64),
    brandName: ar && en ? { ar: clean(ar), en: clean(en) } : null,
    reasons: r.reasons as HuntReason[],
    firstSeen,
    verdict: r.verdict,
    foundBeforeReport: r.found_before_report === true,
    ttdSeconds: ttd !== null && basis !== null ? ttd : null,
    ttdBasis: ttd !== null ? basis : null,
    source,
  };
}

export function parseCounts(raw: unknown): HuntCounts {
  const r = obj(raw);
  const out: HuntCounts = {};
  if (!r) return out;
  for (const k of STATUSES) {
    const v = r[k];
    if (typeof v === "number" && Number.isInteger(v) && v >= 0) out[k as HuntStatus] = v;
  }
  return out;
}

export function parseSources(raw: unknown): HuntSource[] {
  if (!Array.isArray(raw)) return [];
  const out: HuntSource[] = [];
  for (const s of raw) {
    const r = obj(s);
    const id = r ? str(r.id) : null;
    const status = r ? str(r.status) : null;
    if (!r || !id || !SOURCE_IDS.includes(id) || !status || !SOURCE_STATUS.includes(status)) continue;
    out.push({ id, kind: clean(str(r.kind) ?? "", 16), status: status as HuntSourceStatus });
  }
  return out;
}

/** Server side: the two upstream bodies -> the allow-listed public shape. */
export function toPublicHunt(feed: unknown, meta: unknown): PublicHunt {
  const f = obj(feed);
  const m = obj(obj(meta)?.hunt);
  const items = (Array.isArray(f?.items) ? f.items : []).map(parseHuntItem).filter((i): i is HuntItem => i !== null).slice(0, 50);
  return {
    enabled: m ? m.enabled === true : null,
    paused: m ? m.paused === true : false,
    sources: m ? parseSources(m.sources) : [],
    items,
    counts: parseCounts(f?.counts),
  };
}

/** Browser side: the public route body (already allow-listed) is parsed again, never trusted. */
export function parsePublicHunt(raw: unknown): PublicHunt | null {
  const r = obj(raw);
  if (!r || !Array.isArray(r.items)) return null;
  return {
    enabled: r.enabled === true ? true : r.enabled === false ? false : null,
    paused: r.paused === true,
    sources: parseSources(r.sources),
    items: r.items.map(parseHuntItem).filter((i): i is HuntItem => i !== null),
    counts: parseCounts(r.counts),
  };
}

/** Number of candidates the hunt recorded but the arbiter has not confirmed (shown only as a count). */
export const unconfirmedCount = (c: HuntCounts): number => STATUSES.filter((s) => s !== "confirmed").reduce((n, s) => n + (c[s as HuntStatus] ?? 0), 0);

// ---- operator view ---------------------------------------------------------------------------

export type HuntAdminRow = { id: string; domain: string; brandId: string; status: HuntStatus; prescore: number; verdict: string | null; firstSeen: string; source: string };
export type HuntAdmin = { enabled: boolean; paused: boolean; intervalMin: number; prescoreMin: number; quota: { perHour: number; perDay: number }; lastCycleAt: string | null; lastOutcome: string | null; sources: HuntSource[]; counts: HuntCounts; items: HuntAdminRow[] };

export function parseHuntAdmin(raw: unknown): HuntAdmin | null {
  const r = obj(raw);
  if (!r || typeof r.enabled !== "boolean" || typeof r.paused !== "boolean" || !Array.isArray(r.items)) return null;
  const q = obj(r.quota);
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
  const items: HuntAdminRow[] = [];
  for (const it of r.items) {
    const x = obj(it);
    const id = x ? str(x.candidate_id) : null;
    const domain = x ? str(x.domain_defanged) : null;
    const status = x ? str(x.status) : null;
    const firstSeen = x ? str(x.first_seen) : null;
    if (!x || !id || !CANDIDATE_ID.test(id) || !domain || !DEFANGED.test(domain) || !status || !STATUSES.includes(status) || !firstSeen || !ISO.test(firstSeen)) continue;
    const prov = obj(x.provenance);
    items.push({
      id,
      domain,
      brandId: clean(str(x.brand_id) ?? "", 64),
      status: status as HuntStatus,
      prescore: Math.max(0, Math.min(100, Math.round(num(x.prescore)))),
      verdict: x.verdict === "suspicious" || x.verdict === "dangerous" || x.verdict === "no_warning_signs" ? x.verdict : null,
      firstSeen,
      source: prov?.source === "fixture" || prov?.source === "replay" ? (prov.source as string) : "live",
    });
  }
  const last = str(r.last_cycle_at);
  return {
    enabled: r.enabled,
    paused: r.paused,
    intervalMin: num(r.interval_min),
    prescoreMin: num(r.prescore_min),
    quota: { perHour: num(q?.per_hour), perDay: num(q?.per_day) },
    lastCycleAt: last && ISO.test(last) ? last : null,
    lastOutcome: ["ok", "paused", "error", "locked"].includes(str(r.last_cycle_outcome) ?? "") ? (r.last_cycle_outcome as string) : null,
    sources: parseSources(r.sources),
    counts: parseCounts(r.counts),
    items,
  };
}

const ADMIN_PATH = "/v1/admin/hunt";

export async function getHuntAdmin(key: string, signal?: AbortSignal): Promise<{ status: number; admin: HuntAdmin | null }> {
  try {
    const res = await fetch(ADMIN_PATH, { headers: authHeaders(key), credentials: "same-origin", cache: "no-store", signal });
    return { status: res.status, admin: res.ok ? parseHuntAdmin(await res.json()) : null };
  } catch {
    return { status: 0, admin: null };
  }
}

export async function putHuntPaused(key: string, paused: boolean): Promise<{ status: number; admin: HuntAdmin | null }> {
  try {
    const res = await fetch(ADMIN_PATH, {
      method: "PUT",
      headers: { ...authHeaders(key), "content-type": "application/json" },
      body: JSON.stringify({ paused }),
      credentials: "same-origin",
      cache: "no-store",
    });
    return { status: res.status, admin: res.ok ? parseHuntAdmin(await res.json()) : null };
  } catch {
    return { status: 0, admin: null };
  }
}
