/**
 * Local-route DSPy before/after rows. Read only from lib/dspy.generated.json, which scripts/sync-results.mjs copies from
 * evals/results/published/dspy/*.json. Empty when no such artifact is on the tree: then no table is shown and no number is typed here.
 */
import raw from "./dspy.generated.json";

export interface DspyRow {
  artifact: string;
  role: string;
  model: string;
  synthetic: boolean;
  adopted: boolean;
  before: number;
  after: number;
  /** Paired 95% interval of the difference, when recorded. */
  low: number | null;
  high: number | null;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function parseDspyRows(file: unknown): DspyRow[] {
  if (!Array.isArray(file)) return [];
  const out: DspyRow[] = [];
  for (const r of file as Record<string, unknown>[]) {
    const b = num((r.before as { mean?: unknown } | undefined)?.mean);
    const a = num((r.after as { mean?: unknown } | undefined)?.mean);
    if (b === null || a === null || typeof r.role !== "string" || typeof r.artifact !== "string") continue;
    const ci = ((r.paired as { ci95?: unknown } | null)?.ci95 ?? null) as unknown[] | null;
    out.push({ artifact: r.artifact, role: r.role, model: typeof r.model === "string" ? r.model : "", synthetic: r.synthetic === true, adopted: r.adopted === true, before: b, after: a, low: ci ? num(ci[0]) : null, high: ci ? num(ci[1]) : null });
  }
  return out;
}

export const bundledDspyRows = (): DspyRow[] => parseDspyRows(raw);
/** True only when the recorded paired interval exists and excludes zero. */
export const excludesZero = (r: DspyRow): boolean => r.low !== null && r.high !== null && (r.low > 0 || r.high < 0);
