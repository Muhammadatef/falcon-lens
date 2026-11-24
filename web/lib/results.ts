/**
 * The published evaluation artifact, as bundled by scripts/sync-results.mjs into
 * lib/results.generated.json. This module only formats what the artifact holds; it never
 * supplies a number of its own. When the file says `available: false` the Results page says
 * "evaluation in progress".
 */
import raw from "./results.generated.json";
import type { Lang } from "./contracts";

export type Split = "test" | "val";
export interface MetricRow {
  key: string;
  value: number;
  lo: number | null;
  hi: number | null;
}
export interface SplitView {
  split: Split;
  n: number;
  rows: MetricRow[];
  officialFalseDangerous: number | null;
}
export interface ResultsView {
  artifact: string;
  createdAt: string;
  datasetHash: string;
  scope: string;
  gitSha: string;
  temporalCut: boolean;
  nBootstrap: number | null;
  splits: SplitView[];
  notEvaluated: string[];
}

const METRICS = ["precision", "recall", "f1", "accuracy", "fpr", "roc_auc", "pr_auc", "ece"] as const;
export const PERCENT_METRICS = new Set<string>(["precision", "recall", "f1", "accuracy", "fpr", "roc_auc", "pr_auc"]);

type Loose = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function parseResults(file: unknown): ResultsView | null {
  const f = file as { available?: boolean; artifact?: string; data?: Loose } | null;
  if (!f || f.available !== true || !f.data) return null;
  const d = f.data;
  const metrics = (d.metrics ?? {}) as Loose;
  const splits: SplitView[] = [];
  for (const split of ["test", "val"] as const) {
    const n = num(metrics[`${split}.n`]);
    if (n === null) continue;
    const rows: MetricRow[] = [];
    for (const key of METRICS) {
      const value = num(metrics[`${split}.${key}`]);
      if (value === null) continue;
      const ci = metrics[`${split}.${key}_ci95`];
      const lo = Array.isArray(ci) ? num(ci[0]) : null;
      const hi = Array.isArray(ci) ? num(ci[1]) : null;
      rows.push({ key, value, lo, hi });
    }
    splits.push({ split, n, rows, officialFalseDangerous: num(metrics[`${split}.official_false_dangerous`]) });
  }
  if (splits.length === 0) return null;
  const seeds = (d.seeds ?? {}) as Loose;
  return {
    artifact: String(f.artifact ?? ""),
    createdAt: String(d.created_at ?? ""),
    datasetHash: String(d.dataset_hash ?? ""),
    scope: String(d.scope ?? ""),
    gitSha: String(d.git_sha ?? ""),
    temporalCut: d.temporal_cut === true,
    nBootstrap: num(seeds.n_bootstrap),
    splits,
    notEvaluated: Array.isArray(d.not_evaluated) ? d.not_evaluated.filter((x): x is string => typeof x === "string") : [],
  };
}

export const loadResults = (): ResultsView | null => parseResults(raw);

/** Percent metrics with one decimal; calibration error as a plain decimal. Presentation only. */
export function formatMetric(key: string, value: number, lang: Lang): string {
  const locale = lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB";
  if (PERCENT_METRICS.has(key)) return `${(value * 100).toLocaleString(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  return value.toLocaleString(locale, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
}

export function formatCi(row: MetricRow, lang: Lang): string {
  if (row.lo === null || row.hi === null) return "";
  return `${formatMetric(row.key, row.lo, lang)} – ${formatMetric(row.key, row.hi, lang)}`;
}

/** The three numbers shown on Home and at the top of Results: test split only, never typed. */
export interface Headline {
  recall: MetricRow;
  fpr: MetricRow;
  official: number;
  n: number;
  artifact: string;
}

/** `null` when the artifact is unavailable or any of the four fields is missing (then no number renders at all). */
export function headline(view: ResultsView | null): Headline | null {
  const test = view?.splits.find((s) => s.split === "test");
  if (!view || !test) return null;
  const recall = test.rows.find((r) => r.key === "recall");
  const fpr = test.rows.find((r) => r.key === "fpr");
  if (!recall || !fpr || test.officialFalseDangerous === null) return null;
  return { recall, fpr, official: test.officialFalseDangerous, n: test.n, artifact: view.artifact };
}
