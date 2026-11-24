/**
 * View models for the /results KPI sections: headline KPIs (validation and test side by side), real vs synthetic,
 * held-out live false alarms by date, red-team per category, and cost and operations.
 * Every figure comes from a bundled artifact (lib/results.generated.json, lib/results-extra.generated.json,
 * lib/eval-areas.generated.json); this module only labels and formats. Copy here carries no digits.
 */
import extra from "./results-extra.generated.json";
import { AR_NOTES } from "./artifact-notes-ar";
import type { Lang } from "./contracts";
import { loadResults, type ResultsView } from "./results";
import { loadAreas, rowText, type Area, type AreaRow } from "./results-areas";

export type Badge = "REAL" | "SYNTHETIC" | "FIXTURE" | "MIXED";
type Bilingual = { ar: string; en: string };

/** REAL / SYNTHETIC / FIXTURE from an artifact's own provenance text; mirrors scripts/results-extra.mjs badgeOf. */
export function badgeOf(provenance: string, fallback: Badge): Badge {
  const text = provenance.replace(/\bnot real\b/gi, "");
  const real = /\breal\b/i.test(text);
  const synth = /fixture|demo bank|synthetic/i.test(text);
  if (real && synth) return "MIXED";
  if (/fixture|demo bank/i.test(text)) return "FIXTURE";
  if (/synthetic/i.test(text)) return "SYNTHETIC";
  if (real) return "REAL";
  return fallback;
}

export const BADGE_LABEL: Record<Badge, Bilingual> = {
  REAL: { ar: "حقيقي · REAL", en: "REAL" },
  SYNTHETIC: { ar: "اصطناعي · SYNTHETIC", en: "SYNTHETIC" },
  FIXTURE: { ar: "نماذج اختبار · FIXTURE", en: "FIXTURE" },
  MIXED: { ar: "مختلط · MIXED", en: "MIXED" },
};
export const BADGE_HELP: Record<Badge, Bilingual> = {
  REAL: { ar: "عناصر حقيقية من العالم الفعلي", en: "Real-world items" },
  SYNTHETIC: { ar: "نصوص اصطناعية كتبناها", en: "Synthetic items we wrote" },
  FIXTURE: { ar: "مواقع اختبار مخترَعة لبنك وهمي", en: "Invented test pages for a demo bank" },
  MIXED: { ar: "بيانات حقيقية واصطناعية معاً، تُقرأ صفاً صفاً", en: "Real and synthetic data together; read row by row" },
};

/** Per-area fallback when the artifact's provenance names neither real nor synthetic, and per-row overrides where one area mixes both. */
const AREA_FALLBACK: Record<string, Badge> = { fit_model_cap: "REAL", arabic_clarity: "FIXTURE" };
const ROW_BADGE: Record<string, (key: string) => Badge | null> = {
  synthetic_split: (k) => (k.startsWith("real_") ? "REAL" : k.startsWith("synthetic_url") ? "FIXTURE" : k.startsWith("synthetic_message") ? "SYNTHETIC" : null),
  sandbox_t2: (k) => (k.startsWith("render_") ? "REAL" : k.startsWith("fixture_") ? "FIXTURE" : null),
};
export function areaRowBadge(area: Area, key: string): Badge {
  return ROW_BADGE[area.id]?.(key) ?? badgeOf(area.provenance, AREA_FALLBACK[area.id] ?? "FIXTURE");
}

const locale = (lang: Lang) => (lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB");
export const pct = (v: number, lang: Lang) => `${(v * 100).toLocaleString(locale(lang), { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const dec3 = (v: number, lang: Lang) => v.toLocaleString(locale(lang), { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const OF: Bilingual = { ar: "من", en: "of" };

export interface Fig {
  main: string;
  detail: string;
  ci: string;
}
interface Row {
  value: number;
  k: number | null;
  n: number | null;
  lo: number | null;
  hi: number | null;
}
function rateFig(r: Row | null | undefined, lang: Lang, fmt: (v: number, l: Lang) => string = pct): Fig | null {
  if (!r || typeof r.value !== "number") return null;
  const detail = r.k !== null && r.n !== null ? `${r.k} ${OF[lang]} ${r.n}` : r.n !== null ? `n = ${r.n}` : "";
  const ci = r.lo !== null && r.hi !== null ? `${fmt(r.lo, lang)} – ${fmt(r.hi, lang)}` : "";
  return { main: fmt(r.value, lang), detail, ci };
}
/** A published count shown as `k of n`, always together (red team: harmful with the answered count beside it). */
const countFig = (k: number, n: number, lang: Lang) => `${k} ${OF[lang]} ${n}`;

// ───────── 1. Headline KPIs ─────────
interface KpiDef {
  key: string;
  label: Bilingual;
  explain: Bilingual;
  /** Where the per-KPI k/n comes from in the real re-score of the same frozen split. */
  countFrom?: "recallWarning" | "fprWarning" | "precisionWarning";
  fmt: (v: number, l: Lang) => string;
}
const KPI_DEFS: KpiDef[] = [
  { key: "recall", label: { ar: "الاستدعاء (Recall)", en: "Recall" }, explain: { ar: "من الروابط الاحتيالية الفعلية، كم منها نبّهنا عليه.", en: "Of the real scams, how many we warned about." }, countFrom: "recallWarning", fmt: pct },
  { key: "precision", label: { ar: "الدقة (Precision)", en: "Precision" }, explain: { ar: "من الروابط التي حذّرنا منها، كم منها كان احتيالاً فعلاً.", en: "Of the links we warned about, how many were really scams." }, countFrom: "precisionWarning", fmt: pct },
  { key: "f1", label: { ar: "مقياس F1", en: "F1 score" }, explain: { ar: "رقم واحد يجمع الدقة والاستدعاء.", en: "One number that balances precision and recall." }, fmt: pct },
  { key: "accuracy", label: { ar: "الصحة الكلية (Accuracy)", en: "Accuracy" }, explain: { ar: "نسبة الأحكام الصحيحة من جميع الروابط.", en: "Share of all links judged correctly." }, fmt: pct },
  { key: "fpr", label: { ar: "الإنذار الخاطئ (FPR)", en: "False-alarm rate (FPR)" }, explain: { ar: "من الروابط السليمة، كم منها نبّهنا عليه خطأً.", en: "Of the legitimate links, how many we warned about by mistake." }, countFrom: "fprWarning", fmt: pct },
  { key: "roc_auc", label: { ar: "ROC-AUC", en: "ROC-AUC" }, explain: { ar: "هل تضع الدرجات الاحتيال فوق السليم؟ الأعلى أفضل.", en: "Do the scores rank scams above legitimate links? Higher is better." }, fmt: pct },
  { key: "pr_auc", label: { ar: "PR-AUC", en: "PR-AUC" }, explain: { ar: "مثل السابق، لكن بتركيز على الدقة والاستدعاء.", en: "Same idea, focused on precision and recall." }, fmt: pct },
  { key: "ece", label: { ar: "خطأ المعايرة (ECE)", en: "Calibration error (ECE)" }, explain: { ar: "الفرق بين الثقة المعلنة والصحة الفعلية. الأقل أفضل.", en: "Gap between stated confidence and actual accuracy. Lower is better." }, fmt: dec3 },
];

export interface KpiCell {
  split: "val" | "test";
  fig: Fig;
}
export interface KpiRow {
  key: string;
  label: string;
  explain: string;
  cells: KpiCell[];
}
export interface KpiGrid {
  artifact: string;
  badge: Badge;
  scope: string;
  n: Record<"val" | "test", number>;
  rows: KpiRow[];
  official: Record<"val" | "test", number | null>;
  /** True when the counts shown come from the synthetic_split re-score, which matches the main artifact. */
  countsFromReScore: boolean;
}

type ExtraSplit = Record<string, Row | number | undefined> | null | undefined;
const ex = extra as unknown as {
  available?: boolean;
  main?: { artifact: string; badge: Badge; scope: string } | null;
  realSynthetic?: {
    artifact: string;
    date: string;
    provenance: string;
    separationRule: string;
    manifest: { real: number | null; synthetic: number | null; realBySplit: Record<string, { legit: number; phishing: number }> };
    matchesMain: boolean;
    real: { val?: ExtraSplit; test?: ExtraSplit };
    syntheticUrls?: ExtraSplit;
    syntheticUrlsCaveat: string;
    syntheticMessages?: ExtraSplit;
    badges: { real: Badge; syntheticUrls: Badge; syntheticMessages: Badge };
  };
  messageText?: { artifact: string; date: string; provenance: string; badge: Badge; val?: MsgSplit; test?: MsgSplit };
  fpHistory?: FpRun[];
  redteam?: Record<string, RtBudget>;
  extractor?: Extractor;
};
interface MsgSplit {
  n: number | null;
  nScam: number | null;
  nLegit: number | null;
  recall?: Row;
  fpr?: Row;
}
export interface FpRun {
  artifact: string;
  date: string;
  set: string;
  sha: string;
  n: number | null;
  all: Row | null;
  web: Row | null;
  noWeb: Row | null;
  falseDangerous: number | null;
  partialReads: number | null;
  postHoc: boolean;
  changes: { count: number; subjects: string[] } | null;
  badge: Badge;
}
interface RtBudget {
  artifact: string;
  date: string;
  provenance: string;
  badge: Badge;
  overall: RtCat;
  categories: Record<string, RtCat>;
}
interface RtCat {
  cases: number;
  harmful: number;
  answered: number;
  lo: number | null;
  hi: number | null;
}
interface ExtractorRoute {
  model: string;
  n: number | null;
  rows: Record<string, Row>;
}
interface Extractor {
  artifact: string;
  date: string;
  provenance: string;
  badge: Badge;
  cloud: ExtractorRoute | null;
  local: ExtractorRoute | null;
  agreement: Record<string, Row>;
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const same = (a: number, b: number) => Math.abs(a - b) < 1e-6;

export function buildKpiGrid(view: ResultsView | null, lang: Lang): KpiGrid | null {
  if (!view) return null;
  const val = view.splits.find((s) => s.split === "val");
  const test = view.splits.find((s) => s.split === "test");
  if (!val || !test) return null;
  const rs = ex.realSynthetic;
  const rows: KpiRow[] = [];
  for (const def of KPI_DEFS) {
    const cells: KpiCell[] = [];
    for (const sv of [val, test]) {
      const m = sv.rows.find((r) => r.key === def.key);
      if (!m) continue;
      let k: number | null = null;
      let n: number | null = sv.n;
      const re = def.countFrom && rs?.matchesMain ? (rs.real[sv.split]?.[def.countFrom] as Row | undefined) : undefined;
      if (re && same(re.value, m.value)) {
        k = re.k;
        n = re.n;
      }
      const fig = rateFig({ value: m.value, k, n, lo: m.lo, hi: m.hi }, lang, def.fmt);
      if (fig) cells.push({ split: sv.split, fig });
    }
    if (cells.length > 0) rows.push({ key: def.key, label: def.label[lang], explain: def.explain[lang], cells });
  }
  return {
    artifact: view.artifact,
    badge: ex.main?.badge ?? badgeOf(view.scope, "REAL"),
    scope: view.scope,
    n: { val: val.n, test: test.n },
    rows,
    official: { val: val.officialFalseDangerous, test: test.officialFalseDangerous },
    countsFromReScore: Boolean(rs?.matchesMain),
  };
}
export const loadKpiGrid = (lang: Lang) => buildKpiGrid(loadResults(), lang);

// ───────── 2. Real vs synthetic ─────────
export interface RsColumn {
  key: string;
  label: string;
  /** Example counts of this column, e.g. "142 scam · 104 legitimate". */
  counts: string;
}
export interface RsMetric {
  key: string;
  label: string;
  /** One figure per column (null when the artifact has none). */
  figs: (Fig | null)[];
  badge: Badge;
}
export interface RsGroup {
  id: string;
  title: string;
  badge: Badge;
  columns: RsColumn[];
  metrics: RsMetric[];
  caveat: string;
}
export interface RealSynthetic {
  artifact: string;
  messageArtifact: string;
  provenance: string;
  separationRule: string;
  realTotal: number | null;
  syntheticTotal: number | null;
  real: RsGroup[];
  synthetic: RsGroup[];
}

const RS_COPY = {
  recallWarning: { ar: "احتيال نُبّه عليه", en: "Scams warned" },
  fprWarning: { ar: "سليم نُبّه عليه خطأً", en: "False alarms" },
  precisionWarning: { ar: "تنبيهات صحيحة (الدقة)", en: "Correct warnings (precision)" },
  recall: { ar: "احتيال نُبّه عليه", en: "Scams warned" },
  fpr: { ar: "سليم نُبّه عليه خطأً", en: "False alarms" },
  val: { ar: "التحقق", en: "Validation" },
  test: { ar: "الاختبار", en: "Test" },
  all: { ar: "الكل", en: "All" },
  legit: { ar: "سليم", en: "legitimate" },
  phishing: { ar: "احتيالي", en: "scam" },
  realT: { ar: "حقيقي: إعادة تقييم المجموعة المجمدة", en: "Real: the frozen split re-scored" },
  urls: { ar: "اصطناعي: روابط نماذج الاختبار", en: "Synthetic: demo-bank test links" },
  msgs: { ar: "اصطناعي: رسائل نصية (مجموعة الفصل)", en: "Synthetic: text messages (split suite)" },
  mt: { ar: "رسائل نصية اصطناعية (مؤلف واحد)", en: "Synthetic text messages (single author)" },
} satisfies Record<string, Bilingual>;

type RsKey = "recallWarning" | "fprWarning" | "precisionWarning";

export function buildRealSynthetic(lang: Lang): RealSynthetic | null {
  const rs = ex.realSynthetic;
  if (!rs) return null;
  const c = RS_COPY;
  const counts = (nPh: unknown, nLe: unknown) => [num(nPh) !== null ? `${num(nPh)} ${c.phishing[lang]}` : "", num(nLe) !== null ? `${num(nLe)} ${c.legit[lang]}` : ""].filter(Boolean).join(" · ");
  const group = (id: string, title: string, badge: Badge, cols: { key: "val" | "test" | "all"; s: ExtraSplit }[], keys: RsKey[], caveat = ""): RsGroup => ({
    id,
    title,
    badge,
    columns: cols.map((x) => ({ key: x.key, label: c[x.key][lang], counts: counts(x.s?.nPhishing, x.s?.nLegit) })),
    metrics: keys.flatMap((key) => {
      const figs = cols.map((x) => rateFig(x.s?.[key] as Row | undefined, lang));
      return figs.some(Boolean) ? [{ key, label: c[key][lang], figs, badge }] : [];
    }),
    caveat,
  });
  const real: RsGroup[] = [];
  const cols = (["val", "test"] as const).flatMap((k) => (rs.real[k] ? [{ key: k, s: rs.real[k] }] : []));
  if (cols.length) real.push(group("real-split", c.realT[lang], rs.badges.real, cols, ["recallWarning", "fprWarning", "precisionWarning"]));
  const synthetic: RsGroup[] = [];
  if (rs.syntheticUrls) synthetic.push(group("synthetic-urls", c.urls[lang], rs.badges.syntheticUrls, [{ key: "all", s: rs.syntheticUrls }], ["recallWarning", "fprWarning", "precisionWarning"], rs.syntheticUrlsCaveat));
  if (rs.syntheticMessages) synthetic.push(group("synthetic-messages", c.msgs[lang], rs.badges.syntheticMessages, [{ key: "all", s: rs.syntheticMessages }], ["recallWarning", "fprWarning"]));
  const mt = ex.messageText;
  if (mt) {
    const as = (s: MsgSplit | undefined): ExtraSplit => (s ? { nPhishing: s.nScam ?? undefined, nLegit: s.nLegit ?? undefined, recallWarning: s.recall, fprWarning: s.fpr } : undefined);
    const mcols = (["val", "test"] as const).flatMap((k) => (mt[k] ? [{ key: k, s: as(mt[k]) }] : []));
    const g = group("message-text", c.mt[lang], mt.badge, mcols, ["recallWarning", "fprWarning"]);
    g.metrics = g.metrics.map((m) => ({ ...m, label: m.key === "recallWarning" ? c.recall[lang] : c.fpr[lang] }));
    synthetic.push(g);
  }
  return {
    artifact: rs.artifact,
    messageArtifact: mt?.artifact ?? "",
    provenance: rs.provenance,
    separationRule: rs.separationRule,
    realTotal: rs.manifest.real,
    syntheticTotal: rs.manifest.synthetic,
    real,
    synthetic,
  };
}

// ───────── 3. Real websites never seen before ─────────
export interface FpRunView {
  artifact: string;
  date: string;
  setLabel: string;
  sha: string;
  reRun: boolean;
  newest: boolean;
  all: Fig | null;
  web: Fig | null;
  noWeb: Fig | null;
  dangerous: number | null;
  postHoc: boolean;
  changeCount: number | null;
  changes: string[];
  badge: Badge;
}
export interface FpHistory {
  runs: FpRunView[];
  /** Oldest first: points for the sparkline (rates straight from the artifacts). */
  series: { all: (number | null)[]; web: (number | null)[]; lo: (number | null)[]; hi: (number | null)[] };
  anyPostHoc: boolean;
}
const setNumber = (set: string): string => /heldout_legit_(\d+)/.exec(set)?.[1] ?? set;
const SET: Bilingual = { ar: "المجموعة", en: "Set" };

export function buildFpHistory(lang: Lang): FpHistory | null {
  const runs = ex.fpHistory;
  if (!runs || runs.length === 0) return null;
  const seen = new Set<string>();
  const views: FpRunView[] = runs.map((r, i) => {
    const reRun = seen.has(r.set);
    seen.add(r.set);
    return {
      artifact: r.artifact,
      date: r.date.slice(0, 10),
      setLabel: `${SET[lang]} ${setNumber(r.set)}`,
      sha: r.sha,
      reRun,
      newest: i === runs.length - 1,
      all: rateFig(r.all, lang),
      web: rateFig(r.web, lang),
      noWeb: rateFig(r.noWeb, lang),
      dangerous: r.falseDangerous,
      postHoc: r.postHoc,
      changeCount: r.changes?.count ?? null,
      changes: r.changes?.subjects ?? [],
      badge: r.badge,
    };
  });
  return {
    runs: views.slice().reverse(),
    series: { all: runs.map((r) => r.all?.value ?? null), web: runs.map((r) => r.web?.value ?? null), lo: runs.map((r) => r.all?.lo ?? null), hi: runs.map((r) => r.all?.hi ?? null) },
    anyPostHoc: runs.some((r) => r.postHoc),
  };
}

// ───────── 4. Attacks ─────────
export interface AttackRow {
  category: string;
  label: string;
  /** `harmful of cases`, and the answered count always beside it. */
  harmful: string;
  answered: string;
  ci: string;
}
export interface AttackBudget {
  budget: "extended" | "production";
  artifact: string;
  date: string;
  badge: Badge;
  rows: AttackRow[];
  total: AttackRow;
}
const CATEGORY: Record<string, Bilingual> = {
  page: { ar: "صفحات", en: "Pages" },
  message: { ar: "رسائل", en: "Messages" },
  url: { ar: "روابط", en: "Links" },
  email: { ar: "بريد إلكتروني", en: "Email" },
  image: { ar: "صور", en: "Images" },
};
export const CATEGORY_ORDER = ["page", "message", "url", "email", "image"];

export function buildAttacks(lang: Lang): AttackBudget[] {
  const rt = ex.redteam ?? {};
  const total: Bilingual = { ar: "المجموع", en: "All" };
  const one = (category: string, label: string, v: RtCat): AttackRow => ({
    category,
    label,
    harmful: countFig(v.harmful, v.cases, lang),
    answered: countFig(v.answered, v.cases, lang),
    ci: v.lo !== null && v.hi !== null ? `${pct(v.lo, lang)} – ${pct(v.hi, lang)}` : "",
  });
  return (["extended", "production"] as const).flatMap((budget) => {
    const b = rt[budget];
    if (!b) return [];
    const cats = CATEGORY_ORDER.filter((c) => b.categories[c]);
    const rows = cats.map((c) => one(c, (CATEGORY[c] ?? { ar: c, en: c })[lang], b.categories[c]!));
    return [{ budget, artifact: b.artifact, date: b.date, badge: b.badge, rows, total: one("all", total[lang], b.overall) }];
  });
}

// ───────── 5. Cost and operations ─────────
export interface OpsRow {
  key: string;
  label: string;
  fig: Fig;
  badge: Badge;
  artifact: string;
}
export interface ExtractorView {
  artifact: string;
  badge: Badge;
  columns: { route: "cloud" | "local"; model: string }[];
  rows: { key: string; label: string; cloud: Fig | null; local: Fig | null }[];
  agreement: { key: string; label: string; fig: Fig }[];
}
export interface Ops {
  cost: OpsRow[];
  agreement: OpsRow[];
  stability: OpsRow[];
  extractor: ExtractorView | null;
}
const EXTRACTOR_ROWS: { key: string; label: Bilingual }[] = [
  { key: "all_four", label: { ar: "الحقول الأربعة صحيحة كلها", en: "All four fields exact" } },
  { key: "brand", label: { ar: "الجهة المنتحَلة", en: "Claimed organisation" } },
  { key: "language", label: { ar: "اللغة", en: "Language" } },
  { key: "script", label: { ar: "نوع الكتابة", en: "Writing system" } },
  { key: "no_extraction", label: { ar: "تعذّر الاستخراج", en: "No extraction" } },
];
const AGREE_LABEL: Record<string, Bilingual> = {
  brand: { ar: "اتفاق المسارين: الجهة", en: "Routes agree: organisation" },
  language: { ar: "اتفاق المسارين: اللغة", en: "Routes agree: language" },
  requested_data: { ar: "اتفاق المسارين: البيانات المطلوبة", en: "Routes agree: requested data" },
  script: { ar: "اتفاق المسارين: نوع الكتابة", en: "Routes agree: writing system" },
};
const OPS_LABEL: Record<string, Bilingual> = {
  cloud_usd_per_check: { ar: "كلفة الفحص الواحد (السحابي، دولار)", en: "Cost per check (cloud, USD)" },
  cloud_usd_per_1000: { ar: "الكلفة لكل ألف فحص (السحابي، دولار)", en: "Cost per thousand checks (cloud, USD)" },
  local_usd_per_check: { ar: "كلفة الواجهة الإضافية (المحلي، دولار)", en: "Marginal API cost (local, USD)" },
  exact_label_agreement: { ar: "اتفاق الحكم بين السحابي والمحلي", en: "Same verdict, cloud vs local" },
  ai_on_all_three_identical: { ar: "ثبات الحكم في ثلاث مرات", en: "Same verdict in three runs" },
  ai_on_among_completed: { ar: "الثبات بين المرات المكتملة", en: "Same verdict among completed runs" },
};

function opsRows(areas: Area[], area: string, keys: string[], lang: Lang): OpsRow[] {
  const a = areas.find((x) => x.id === area);
  if (!a) return [];
  return keys.flatMap((key) => {
    const r: AreaRow | undefined = a.rows[key];
    if (!r) return [];
    const t = rowText(r, lang);
    return [{ key, label: OPS_LABEL[key]?.[lang] ?? key, fig: { main: t.main, detail: t.detail, ci: t.ci }, badge: areaRowBadge(a, key), artifact: a.artifact }];
  });
}

export function buildOps(lang: Lang, areas: Area[] = loadAreas()): Ops {
  const e = ex.extractor;
  const extractor: ExtractorView | null = e
    ? {
        artifact: e.artifact,
        badge: e.badge,
        columns: [e.cloud ? { route: "cloud" as const, model: e.cloud.model } : null, e.local ? { route: "local" as const, model: e.local.model } : null].filter((x): x is { route: "cloud" | "local"; model: string } => x !== null),
        rows: EXTRACTOR_ROWS.flatMap((r) => {
          const cloud = rateFig(e.cloud?.rows[r.key], lang);
          const local = rateFig(e.local?.rows[r.key], lang);
          return cloud || local ? [{ key: r.key, label: r.label[lang], cloud, local }] : [];
        }),
        agreement: Object.keys(AGREE_LABEL).flatMap((key) => {
          const fig = rateFig(e.agreement[key], lang);
          return fig ? [{ key, label: AGREE_LABEL[key]![lang], fig }] : [];
        }),
      }
    : null;
  return {
    cost: opsRows(areas, "cost_per_check", ["cloud_usd_per_check", "cloud_usd_per_1000", "local_usd_per_check"], lang),
    agreement: opsRows(areas, "route_compare", ["exact_label_agreement"], lang),
    stability: opsRows(areas, "stability", ["ai_on_all_three_identical", "ai_on_among_completed"], lang),
    extractor,
  };
}

/** Copy for the section headings, scopes and notes. Numberless; no claim of "safe". */
export const KPI_COPY = {
  ar: {
    kpiTitle: "المؤشرات الرئيسية",
    kpiLead: "كاشف الروابط المُشحون على مجموعتين منفصلتين: التحقق (ضُبطت عليها العتبات) والاختبار (قُرئت للتقييم). كل مؤشر معه عدد الأمثلة ونطاق الثقة 95%.",
    legend: "تحت كل رقم: عدد الأمثلة ثم نطاق الثقة 95%.",
    kpiScope: "النطاق: تحليل العنوان مع المحكّم على روابط حقيقية، دون اتصال، دون نموذج لغوي ودون زيارة الصفحة.",
    kpiCounts: "عدد أمثلة كل مؤشر من إعادة تقييم المجموعة المجمدة نفسها، وهي تطابق الملف الرئيسي.",
    val: "التحقق",
    test: "الاختبار",
    official: "مواقع رسمية صُنّفت خطِرة خطأً",
    officialHelp: "عدد المواقع الرسمية التي وُسمت «خطِر» خطأً.",
    examples: "أمثلة",
    ci: "نطاق الثقة 95%",
    rsTitle: "حقيقي مقابل اصطناعي",
    rsLead: "لا نجمع الأرقام الحقيقية مع الاصطناعية. لكل رقم في هذه الصفحة وسم يبيّن مصدره.",
    rsReal: "بيانات حقيقية",
    rsSynth: "بيانات اصطناعية",
    manifestReal: "عناصر حقيقية في المجموعة المجمدة",
    manifestSynth: "عناصر اصطناعية في المجموعة المجمدة",
    rsMatches: "تطابق إعادة التقييم الحقيقية الأرقام الرئيسية في الملف الرئيسي.",
    rsSynthNote: "الأرقام الاصطناعية لا تدل على الأداء الميداني: هي نماذج اختبار مخترَعة أو نصوص كتبها مؤلف واحد ودقّقها المشرف.",
    rsCaveat: "تنبيه الملف كما نُشر",
    fpTitle: "مواقع حقيقية لم نرها من قبل",
    fpLead: "مواقع مشروعة حقيقية أُجري عليها الفحص الحي. الإنذار الخاطئ هنا هو موقع مشروع صنّفته الخدمة مشبوهاً أو خطِراً.",
    fpScope: "النطاق: الخدمة الحية كاملة على مجموعات محجوزة من نطاقات مشروعة، وكل صف قراءة منفصلة.",
    fpNote: "المجموعة التي تُقاس مجدداً بعد تعديل الشيفرة لا تبقى غير مرئية لتلك التعديلات؛ تُقرأ صفوفها اللاحقة على هذا الأساس. وسمنا كل قراءة متكررة على المجموعة نفسها.",
    fpAll: "كل المواقع",
    fpShowAll: "عرض كل القراءات:",
    fpWeb: "تقدّم صفحة ويب",
    fpNoWeb: "بلا صفحة ويب",
    fpRun: "القراءة",
    fpNewest: "الأحدث",
    fpReRun: "قراءة متكررة على المجموعة نفسها",
    fpPostHoc: "بعد الاطلاع على النتائج (كما يذكر الملف)",
    fpDangerous: "صُنّفت خطِرة",
    fpChanges: "تعديلات الشيفرة منذ القراءة السابقة",
    fpChangesNone: "لا يوجد سجل للتعديلات",
    fpMore: "وغيرها",
    fpSpark: "الإنذار الخاطئ عبر القراءات من الأقدم إلى الأحدث",
    fpOldest: "الأقدم",
    fpNewestShort: "الأحدث",
    fpCommits: "تعديلاً",
    atkTitle: "الهجمات",
    atkLead: "حالات هجوم مخترَعة تحاول خداع النظام. «ضارّة» تعني أن الهجوم نجح في خفض الحكم أو تسريب نص المهاجم أو تشغيل أداة محظورة. يُعرض معها دائماً عدد ما أجاب عنه النموذج فعلاً.",
    atkScope: "النطاق: مسار الفحص المُشحون بالنموذج المحلي، على حالات اصطناعية فقط، لا هجمات حقيقية.",
    atkNote: "عند المهلة الإنتاجية القصيرة لم يُجب النموذج عن معظم الحالات، فلا يغطي ذلك التشغيل طبقة النموذج. وبعض الفئات لم يُجب النموذج عن أي حالة فيها، فتُقرأ «ضارّة» فيها على أنها لا تقيس تلك الطبقة.",
    atkHarmful: "ضارّة",
    atkAnswered: "أجاب النموذج",
    atkCategory: "الفئة",
    atkExtended: "مهلة ممتدة",
    atkProduction: "مهلة إنتاجية",
    opsTitle: "الكلفة والتشغيل",
    opsLead: "كلفة الفحص الواحد، واتفاق المسارين، ودقة استخراج الحقول، والثبات عند التكرار.",
    opsScope: "النطاق: أمثلة اصطناعية قصيرة. الكلفة من الرموز المستخدمة فعلاً، ولا تشمل البنية التحتية؛ المسار المحلي بلا كلفة واجهة إضافية لا بلا كلفة.",
    opsCost: "الكلفة",
    opsAgree: "اتفاق السحابي والمحلي",
    opsExtract: "دقة استخراج الحقول لكل مسار",
    opsStable: "الثبات عند التكرار",
    cloud: "السحابي",
    local: "المحلي",
    route: "المسار",
    artifact: "ملف التقييم",
    date: "التاريخ",
  },
  en: {
    kpiTitle: "Headline KPIs",
    kpiLead: "The shipped link detector on two separate sets: validation (where thresholds were chosen) and test (read once for scoring). Each KPI shows its example count and 95% range.",
    legend: "Under each figure: the example count, then the 95% range.",
    kpiScope: "Scope: address analysis with the arbiter on real links, offline, no language model and no page visit.",
    kpiCounts: "Example counts come from re-scoring the same frozen split, which matches the main artifact.",
    val: "Validation",
    test: "Test",
    official: "Official sites wrongly rated dangerous",
    officialHelp: "How many official sites were wrongly labelled dangerous.",
    examples: "examples",
    ci: "95% range",
    rsTitle: "Real vs synthetic",
    rsLead: "We never pool real and synthetic numbers. Every figure on this page carries a badge showing where it comes from.",
    rsReal: "Real data",
    rsSynth: "Synthetic data",
    manifestReal: "Real items in the frozen manifest",
    manifestSynth: "Synthetic items in the frozen manifest",
    rsMatches: "The real re-score reproduces the headline figures in the main artifact.",
    rsSynthNote: "Synthetic figures are not field performance: they are invented test pages or texts written by one author and audited by the supervisor.",
    rsCaveat: "Caveat as published",
    fpTitle: "Real websites never seen before",
    fpLead: "Real legitimate websites run through the live service. A false alarm here is a legitimate site the service rated suspicious or dangerous.",
    fpScope: "Scope: the whole live service on held-out sets of legitimate domains; each row is a separate read.",
    fpNote: "A set measured again after code changes is no longer unseen by those changes, so read its later rows that way. Every repeat read on the same set is marked.",
    fpAll: "All sites",
    fpShowAll: "Show all runs:",
    fpWeb: "Serves a web page",
    fpNoWeb: "No web page",
    fpRun: "Run",
    fpNewest: "Newest",
    fpReRun: "Repeat read on the same set",
    fpPostHoc: "Post hoc (as the artifact states)",
    fpDangerous: "rated dangerous",
    fpChanges: "Code changes since the previous run",
    fpChangesNone: "No change log recorded",
    fpMore: "and more",
    fpSpark: "False alarms across runs, oldest to newest",
    fpOldest: "Oldest",
    fpNewestShort: "Newest",
    fpCommits: "changes",
    atkTitle: "Attacks",
    atkLead: "Invented attack cases that try to fool the system. Harmful means the attack lowered the verdict, leaked attacker text or triggered a forbidden tool. The number of cases the model actually answered is always shown beside it.",
    atkScope: "Scope: the shipped cascade on the local model, synthetic cases only, no real attacks.",
    atkNote: "At the short production deadline the model answered most cases not at all, so that run does not cover the model layer. Where a category shows no answered cases, its harmful count does not measure that layer.",
    atkHarmful: "Harmful",
    atkAnswered: "Model answered",
    atkCategory: "Category",
    atkExtended: "Extended deadline",
    atkProduction: "Production deadline",
    opsTitle: "Cost and operations",
    opsLead: "Cost per check, agreement between routes, field-extraction accuracy and stability across repeats.",
    opsScope: "Scope: short synthetic fixtures. Cost is from tokens actually used and excludes infrastructure; the local route has zero marginal API cost, not zero cost.",
    opsCost: "Cost",
    opsAgree: "Cloud and local agreement",
    opsExtract: "Field-extraction accuracy per route",
    opsStable: "Stability across repeats",
    cloud: "Cloud",
    local: "Local",
    route: "Route",
    artifact: "Artifact",
    date: "Date",
  },
} as const;
export const kpiCopy = (lang: Lang) => KPI_COPY[lang];

// ───────── Artifact prose in Arabic ─────────
/** Arabic text of a published artifact note, or null when it has no translation (the UI then shows the English, labelled). */
export function artifactNote(text: string, lang: Lang): string | null {
  if (!text) return null;
  return lang === "en" ? text : (AR_NOTES[text] ?? null);
}
