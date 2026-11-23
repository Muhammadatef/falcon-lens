/**
 * Artifact-driven values for the Docs area (fitted thresholds, provenance). Nothing is typed here:
 * the values are read from lib/results.generated.json, the bundled published evaluation file.
 * When the file says `available: false` or a field is missing, the value is null and the page shows nothing.
 */
import raw from "./results.generated.json";

type Loose = Record<string, unknown>;
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v !== "" ? v : null);

export interface Thresholds {
  tauLow: number;
  tauHigh: number;
  epsLow: number | null;
  epsHigh: number | null;
  fitSource: string | null;
}

export interface Provenance {
  artifact: string;
  createdAt: string | null;
  datasetHash: string | null;
  gitSha: string | null;
  scope: string | null;
}

function dataOf(file: unknown): { artifact: string; data: Loose } | null {
  const f = file as { available?: boolean; artifact?: string; data?: Loose } | null;
  if (!f || f.available !== true || !f.data || typeof f.artifact !== "string") return null;
  return { artifact: f.artifact, data: f.data };
}

export function parseThresholds(file: unknown): Thresholds | null {
  const d = dataOf(file);
  const t = (d?.data.thresholds ?? null) as Loose | null;
  if (!t) return null;
  const tauLow = num(t.tau_low);
  const tauHigh = num(t.tau_high);
  if (tauLow === null || tauHigh === null) return null;
  return { tauLow, tauHigh, epsLow: num(t.eps_low), epsHigh: num(t.eps_high), fitSource: str(t.fit_source) };
}

export function parseProvenance(file: unknown): Provenance | null {
  const d = dataOf(file);
  if (!d) return null;
  return { artifact: d.artifact, createdAt: str(d.data.created_at), datasetHash: str(d.data.dataset_hash), gitSha: str(d.data.git_sha), scope: str(d.data.scope) };
}

/** Western digits in both languages, as everywhere else on the site. */
export const fmtThreshold = (v: number): string => v.toLocaleString("en-US", { maximumFractionDigits: 4 });

export const bundledThresholds = (): Thresholds | null => parseThresholds(raw);
export const bundledProvenance = (): Provenance | null => parseProvenance(raw);
