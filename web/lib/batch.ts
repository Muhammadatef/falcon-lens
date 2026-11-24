/**
 * Batch check helpers shared by the /ops/batch page and its server route. The mapping mirrors
 * scripts/batch_check.py (docs/EVALS.md, "Run your own test set"): strict = dangerous OR suspicious is fraud.
 */
export const BATCH_MAX_URLS = 500;
export const BATCH_MAX_FILE_BYTES = 256 * 1024;
export const BATCH_FIELDS = ["url", "verdict", "risk_score", "binary_label", "degraded", "degraded_reasons", "tier_reached", "top_reasons", "latency_ms", "verdict_id", "error"] as const;

export type BatchMode = "strict" | "lenient";
export type BatchVerdict = "dangerous" | "suspicious" | "no_warning_signs" | "could_not_check";

/** What the server route returns for one URL (no binary label: the mode is applied in the browser). */
export interface BatchResult {
  verdict: BatchVerdict;
  risk_score: number | null;
  degraded: boolean;
  degraded_reasons: string[];
  tier_reached: string;
  top_reasons: string[];
  latency_ms: number;
  verdict_id: string;
  error: string;
}

export function binaryLabel(verdict: BatchVerdict, mode: BatchMode): "fraud" | "legit" {
  if (verdict === "dangerous") return "fraud";
  if (verdict === "suspicious" || verdict === "could_not_check") return mode === "strict" ? "fraud" : "legit";
  return "legit";
}

/** One URL per line (blank and # lines skipped), or a CSV whose header has a `url` column. Duplicates dropped. */
export function parseBatchInput(text: string): string[] {
  const lines = text.replace(/^\u{FEFF}/u, "").split(/\r?\n/);
  const first = lines.find((l) => l.trim() !== "") ?? "";
  const header = splitCsvLine(first).map((h) => h.trim().toLowerCase());
  const col = header.indexOf("url");
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (u: string) => {
    const v = u.trim();
    if (v && !seen.has(v)) {
      seen.add(v);
      out.push(v);
    }
  };
  if (col >= 0) {
    for (const l of lines.slice(lines.indexOf(first) + 1)) if (l.trim()) push(splitCsvLine(l)[col] ?? "");
  } else {
    for (const l of lines) if (l.trim() && !l.trim().startsWith("#")) push(l);
  }
  return out;
}

/** Minimal RFC 4180 line splitter (quotes, doubled quotes). */
export function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      cells.push(cur);
      cur = "";
    } else cur += c;
  }
  cells.push(cur);
  return cells;
}

/** CSV cell: quoted when needed, and neutralised when a spreadsheet would read it as a formula. */
export function csvCell(value: string | number | boolean | null): string {
  let s = value === null ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows: { url: string; result: BatchResult }[], mode: BatchMode): string {
  const lines: string[] = [BATCH_FIELDS.join(",")];
  for (const { url, result: r } of rows) {
    lines.push(
      [url, r.verdict, r.risk_score, binaryLabel(r.verdict, mode), r.verdict === "could_not_check" ? "" : r.degraded, r.degraded_reasons.join(";"), r.tier_reached, r.top_reasons.join(";"), r.latency_ms, r.verdict_id, r.error]
        .map(csvCell)
        .join(","),
    );
  }
  return `${lines.join("\r\n")}\r\n`;
}

export const couldNotCheck = (error: string, latency_ms = 0, verdict_id = ""): BatchResult => ({ verdict: "could_not_check", risk_score: null, degraded: false, degraded_reasons: [], tier_reached: "", top_reasons: [], latency_ms, verdict_id, error });

interface EvidenceLike { id?: string; signal?: string; hard_rule?: string | null; weight?: number; polarity?: string }
interface VerdictLike { verdict?: string; verdict_id?: string; risk_score?: number; degraded?: boolean; degraded_reasons?: string[]; tier_reached?: string; latency_ms?: number; evidence?: EvidenceLike[]; reasons?: { evidence_ids?: string[] }[] }

export function resultFromVerdict(doc: VerdictLike, latencyFallback: number): BatchResult {
  if (doc.verdict !== "dangerous" && doc.verdict !== "suspicious" && doc.verdict !== "no_warning_signs") return couldNotCheck("unexpected verdict", latencyFallback, doc.verdict_id ?? "");
  const byId = new Map((doc.evidence ?? []).map((e) => [e.id, e]));
  const codes: string[] = [];
  const add = (e: EvidenceLike | undefined) => {
    const c = e?.hard_rule || e?.signal;
    if (c && !codes.includes(c)) codes.push(c);
  };
  for (const r of doc.reasons ?? []) for (const id of r.evidence_ids ?? []) add(byId.get(id));
  [...byId.values()].filter((e) => e.polarity === "risk" || (e.weight ?? 0) > 0).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).forEach(add);
  return { verdict: doc.verdict, risk_score: doc.risk_score ?? null, degraded: !!doc.degraded, degraded_reasons: doc.degraded_reasons ?? [], tier_reached: doc.tier_reached ?? "", top_reasons: codes.slice(0, 3), latency_ms: doc.latency_ms ?? latencyFallback, verdict_id: doc.verdict_id ?? "", error: "" };
}
