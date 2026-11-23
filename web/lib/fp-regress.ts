/**
 * The newest live held-out false-alarm measurement (evals/results/published/fp_regress/*.json), bundled by
 * scripts/sync-results.mjs into lib/fp-regress.generated.json. Presentation only: no number is typed here.
 * "Flagged by mistake" = a real, legitimate domain that the live service rated suspicious or dangerous.
 */
import raw from "./fp-regress.generated.json";
import type { Lang } from "./contracts";

export interface FpRow {
  n: number;
  rate: number;
  lo: number;
  hi: number;
}
export interface LiveFp {
  artifact: string;
  createdAt: string;
  web: FpRow;
  all: FpRow;
}

type Loose = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const sum = (o: unknown): number | null => {
  if (typeof o !== "object" || o === null) return null;
  const values = Object.values(o as Loose);
  return values.length > 0 && values.every((v) => num(v) !== null) ? values.reduce<number>((a, b) => a + (b as number), 0) : null;
};

function row(fpr: unknown, n: number | null): FpRow | null {
  const f = fpr as { value?: unknown; ci95?: unknown } | null;
  const rate = num(f?.value);
  const ci = Array.isArray(f?.ci95) ? (f.ci95 as unknown[]) : null;
  const lo = ci ? num(ci[0]) : null;
  const hi = ci ? num(ci[1]) : null;
  return rate === null || lo === null || hi === null || n === null ? null : { n, rate, lo, hi };
}

export function parseLiveFp(file: unknown): LiveFp | null {
  const f = file as { available?: boolean; artifact?: string; data?: Loose } | null;
  if (!f || f.available !== true || !f.data) return null;
  const d = f.data;
  const web = (d.by_serves_web as Loose | undefined)?.serves_web_page as Loose | undefined;
  const w = row(web?.false_positive_rate, num(web?.n));
  const a = row(d.false_positive_rate, num(d.n) ?? sum(d.counts));
  if (!w || !a) return null;
  return { artifact: String(f.artifact ?? ""), createdAt: String(d.created_at ?? ""), web: w, all: a };
}

export const loadLiveFp = (): LiveFp | null => parseLiveFp(raw);

export function formatRate(value: number, lang: Lang): string {
  return `${(value * 100).toLocaleString(lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
}
