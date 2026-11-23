/**
 * Server-side projection for the public campaign board (`/campaigns`).
 *
 * The browser never calls `/v1/campaigns` itself (it needs a read-scope key). The Next.js route
 * handlers under `app/api/public/campaigns` call the API with the service key and pass every
 * campaign through `toPublicCampaign`, an ALLOW-list: only the fields below survive, so actions,
 * drafts, approvers, notes, raw URLs or anything added to the API later never reach a visitor.
 */
import { defang } from "./defang";

export interface PublicCampaign {
  campaign_id: string;
  brand_name: { ar?: string; en?: string } | null;
  title: { ar?: string; en?: string };
  advice: { ar?: string; en?: string };
  severity: "low" | "medium" | "high" | "critical";
  count: number;
  first_seen: string | null;
  last_seen: string | null;
  series: number[];
  source: "live" | "replay" | "synthetic" | "fixture";
  status: string | null;
  /** Defanged domain indicators only (hxxp / [.]), capped. */
  domains: string[];
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
// eslint-disable-next-line no-control-regex
const text = (v: unknown, max = 400): string | undefined => (typeof v === "string" && v.length > 0 ? v.replace(/[\u0000-\u001f\u007f]/g, " ").slice(0, max) : undefined);
const SEVERITIES = ["low", "medium", "high", "critical"] as const;
const SOURCES = ["live", "replay", "synthetic", "fixture"] as const;
const STATUSES = ["open", "triaging", "awaiting_approval", "mitigated", "closed", "false_positive"];
const ID_RE = /^(cmp|inc)_[0-9A-Za-z_]{1,64}$/;
export const MAX_DOMAINS = 8;

function bilingual(obj: Record<string, unknown>, nested: string, flatAr: string, flatEn: string): { ar?: string; en?: string } {
  const n = obj[nested];
  if (isObj(n)) return { ar: text(n.ar), en: text(n.en) };
  return { ar: text(obj[flatAr]), en: text(obj[flatEn]) };
}

function brandName(v: unknown): { ar?: string; en?: string } | null {
  if (isObj(v)) {
    const ar = text(v.ar, 120);
    const en = text(v.en, 120);
    return ar || en ? { ar, en } : null;
  }
  const en = text(v, 120);
  return en ? { en } : null;
}

/** Accepts the contract shape (title_ar/title_en) and the small nested shape; returns null for anything unusable. */
export function toPublicCampaign(raw: unknown): PublicCampaign | null {
  if (!isObj(raw)) return null;
  const id = text(raw.campaign_id, 80) ?? text(raw.id, 80);
  if (!id || !ID_RE.test(id)) return null;
  const count = typeof raw.count === "number" && Number.isFinite(raw.count) ? Math.max(0, Math.round(raw.count)) : 0;
  const series = Array.isArray(raw.series) ? raw.series.filter((v): v is number => typeof v === "number" && Number.isFinite(v) && v >= 0).slice(-24) : [];
  const sev = (SEVERITIES as readonly unknown[]).includes(raw.severity) ? (raw.severity as PublicCampaign["severity"]) : "low";
  const src = (SOURCES as readonly unknown[]).includes(raw.source) ? (raw.source as PublicCampaign["source"]) : "live";
  const status = typeof raw.status === "string" && STATUSES.includes(raw.status) ? raw.status : null;
  const domains = Array.isArray(raw.domains)
    ? raw.domains.filter((d): d is string => typeof d === "string").slice(0, MAX_DOMAINS).map((d) => defang(d.slice(0, 253)))
    : [];
  return {
    campaign_id: id,
    brand_name: brandName(raw.brand_name),
    title: bilingual(raw, "title", "title_ar", "title_en"),
    advice: bilingual(raw, "advice", "advice_ar", "advice_en"),
    severity: sev,
    count,
    first_seen: text(raw.first_seen, 40) ?? null,
    last_seen: text(raw.last_seen, 40) ?? text(raw.updated_at, 40) ?? null,
    series,
    source: src,
    status,
    domains,
  };
}

export function toPublicList(raw: unknown): PublicCampaign[] {
  const list = Array.isArray(raw) ? raw : isObj(raw) && Array.isArray(raw.items) ? raw.items : [];
  return list.map(toPublicCampaign).filter((c): c is PublicCampaign => c !== null).slice(0, 100);
}

/** Re-frames one upstream SSE block: only `campaign`/`message` events pass, with filtered JSON data. */
export function filterFrame(block: string): string | null {
  let event = "message";
  const data: string[] = [];
  let id: string | null = null;
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    else if (line.startsWith("id:")) id = line.slice(3).trim().replace(/[^\w.-]/g, "").slice(0, 64);
  }
  if (data.length === 0 || (event !== "campaign" && event !== "message")) return null;
  try {
    const campaign = toPublicCampaign(JSON.parse(data.join("\n")));
    if (!campaign) return null;
    return `${id ? `id: ${id}\n` : ""}event: campaign\ndata: ${JSON.stringify(campaign)}\n\n`;
  } catch {
    return null;
  }
}

/** Fixed-window per-visitor limiter (in memory, per server instance). */
export class WindowLimiter {
  private hits = new Map<string, { n: number; reset: number }>();
  constructor(private readonly limit: number, private readonly windowMs: number, private readonly maxKeys = 5000) {}
  /** Returns 0 when allowed, else the seconds to wait. */
  take(key: string, now = Date.now()): number {
    if (this.hits.size > this.maxKeys) for (const [k, v] of this.hits) if (v.reset <= now) this.hits.delete(k);
    const cur = this.hits.get(key);
    if (!cur || cur.reset <= now) {
      this.hits.set(key, { n: 1, reset: now + this.windowMs });
      return 0;
    }
    if (cur.n >= this.limit) return Math.max(1, Math.ceil((cur.reset - now) / 1000));
    cur.n += 1;
    return 0;
  }
}

/** Visitor IP as set by the gateway (`X-Falcon-Client-IP`); anything that is not an IP shares one bucket. */
export function visitorKey(request: Request): string {
  const ip = request.headers.get("x-falcon-client-ip")?.trim() ?? "";
  return /^[0-9a-fA-F:.]{2,45}$/.test(ip) ? ip : "unknown";
}
