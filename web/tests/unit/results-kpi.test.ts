import { describe, expect, it } from "vitest";
import areas from "@/lib/eval-areas.generated.json";
import extra from "@/lib/results-extra.generated.json";
import main from "@/lib/results.generated.json";
import { loadResults } from "@/lib/results";
import { badgeOf, buildAttacks, buildFpHistory, buildKpiGrid, buildOps, buildRealSynthetic, CATEGORY_ORDER, KPI_COPY, BADGE_LABEL, type Fig } from "@/lib/results-kpi";

const LANGS = ["ar", "en"] as const;

/** Every number of the bundled JSON files (leaf numbers only), in every form the page may print it. */
function harvest(): Set<number> {
  const out = new Set<number>();
  const add = (v: number) => {
    out.add(v);
    out.add(Number((v * 100).toFixed(1)));
    out.add(Number((v * 100 + 1e-9).toFixed(1)));
    out.add(Number(v.toFixed(3)));
    out.add(Number(v.toPrecision(6)));
    out.add(Number(v.toFixed(6)));
  };
  const walk = (o: unknown) => {
    if (typeof o === "number") add(o);
    else if (Array.isArray(o)) o.forEach(walk);
    else if (o && typeof o === "object") Object.values(o).forEach(walk);
  };
  for (const f of [main, extra, areas]) walk(f);
  return out;
}
const tokens = (s: string) => (s.replace(/,/g, "").match(/\d+(?:\.\d+)?/g) ?? []).map(Number);
const figText = (f: Fig | null) => (f ? `${f.main} ${f.detail} ${f.ci}` : "");

describe("results KPI sections: every displayed number exists in the bundled JSON", () => {
  const known = harvest();
  const check = (label: string, s: string) => {
    for (const t of tokens(s)) expect(known.has(t), `${label}: ${t} in "${s}"`).toBe(true);
  };

  it("headline KPI grid: validation and test, each with n and a 95% range", () => {
    const view = loadResults();
    expect(view).not.toBeNull();
    for (const lang of LANGS) {
      const g = buildKpiGrid(view, lang)!;
      expect(g.rows.map((r) => r.key)).toEqual(["recall", "precision", "f1", "accuracy", "fpr", "roc_auc", "pr_auc", "ece"]);
      for (const r of g.rows) {
        expect(r.cells.map((c) => c.split)).toEqual(["val", "test"]);
        expect(r.explain.length).toBeGreaterThan(10);
        for (const c of r.cells) {
          check(`${r.key}.${c.split}.${lang}`, figText(c.fig));
          expect(c.fig.ci, `${r.key} ${c.split}`).not.toBe("");
          expect(c.fig.detail, `${r.key} ${c.split}`).toMatch(/\d/);
        }
      }
      check("n", `${g.n.val} ${g.n.test}`);
      expect(g.official.val).not.toBeNull();
      expect(g.official.test).not.toBeNull();
    }
  });

  it("recall, false alarms and precision use the re-scored k and n only when they equal the main artifact", () => {
    const g = buildKpiGrid(loadResults(), "en")!;
    const recallVal = g.rows.find((r) => r.key === "recall")!.cells[0]!.fig;
    const m = (main as unknown as { data: { metrics: Record<string, number> } }).data.metrics;
    if (g.countsFromReScore) expect(recallVal.detail).toMatch(/^\d+ of \d+$/);
    expect(recallVal.main).toBe(`${(m["val.recall"]! * 100).toFixed(1)}%`);
  });

  it("real vs synthetic: counts, metrics and a badge on every metric", () => {
    for (const lang of LANGS) {
      const rs = buildRealSynthetic(lang)!;
      expect(rs).not.toBeNull();
      expect(rs.real.length).toBeGreaterThan(0);
      expect(rs.synthetic.length).toBeGreaterThan(0);
      check("totals", `${rs.realTotal} ${rs.syntheticTotal}`);
      for (const g of [...rs.real, ...rs.synthetic]) {
        check(`${g.id} counts`, g.columns.map((x) => x.counts).join(" "));
        expect(g.metrics.length).toBeGreaterThan(0);
        for (const mt of g.metrics) {
          check(`${g.id}.${mt.key}`, mt.figs.map(figText).join(" "));
          expect(["REAL", "SYNTHETIC", "FIXTURE"]).toContain(mt.badge);
        }
      }
      expect(rs.real.every((g) => g.badge === "REAL")).toBe(true);
      expect(rs.synthetic.every((g) => g.badge !== "REAL")).toBe(true);
    }
  });

  it("false-alarm history: every run by date, newest first and highlighted, with all / web / no-web rates", () => {
    for (const lang of LANGS) {
      const h = buildFpHistory(lang)!;
      const src = (extra as unknown as { fpHistory: { artifact: string; date: string }[] }).fpHistory;
      expect(h.runs).toHaveLength(src.length);
      expect(h.runs.map((r) => r.artifact)).toEqual(src.map((r) => r.artifact).reverse());
      expect(h.runs.filter((r) => r.newest)).toHaveLength(1);
      expect(h.runs[0]!.newest).toBe(true);
      for (const r of h.runs) {
        check(`${r.artifact} all`, figText(r.all));
        check(`${r.artifact} web`, figText(r.web));
        check(`${r.artifact} noweb`, figText(r.noWeb));
        expect(r.all).not.toBeNull();
        if (r.changeCount !== null) check("changes", String(r.changeCount));
      }
      // The newest run carries the serves-web split.
      expect(h.runs[0]!.web).not.toBeNull();
      expect(h.runs[0]!.noWeb).not.toBeNull();
      // The same set read again after code changes is marked as a repeat.
      expect(h.runs.some((r) => r.reRun)).toBe(true);
    }
  });

  it("attacks: all five categories, harmful always beside the answered count", () => {
    for (const lang of LANGS) {
      const budgets = buildAttacks(lang);
      expect(budgets.length).toBeGreaterThan(0);
      for (const b of budgets) {
        expect(b.rows.map((r) => r.category)).toEqual(CATEGORY_ORDER);
        for (const r of [...b.rows, b.total]) {
          check(`${b.budget}.${r.category}`, `${r.harmful} ${r.answered} ${r.ci}`);
          expect(r.harmful).toMatch(/\d+ \S+ \d+/);
          expect(r.answered).toMatch(/\d+ \S+ \d+/);
        }
      }
    }
  });

  it("cost and operations: cost per check, agreement, extractor per route, stability", () => {
    for (const lang of LANGS) {
      const o = buildOps(lang);
      expect(o.cost.map((r) => r.key)).toEqual(["cloud_usd_per_check", "cloud_usd_per_1000", "local_usd_per_check"]);
      expect(o.agreement).toHaveLength(1);
      expect(o.stability.length).toBeGreaterThan(0);
      expect(o.extractor!.columns.map((c) => c.route)).toEqual(["cloud", "local"]);
      for (const r of [...o.cost, ...o.agreement, ...o.stability]) {
        check(r.key, figText(r.fig));
        expect(["REAL", "SYNTHETIC", "FIXTURE", "MIXED"]).toContain(r.badge);
      }
      for (const r of o.extractor!.rows) {
        check(`extractor ${r.key}`, `${figText(r.cloud)} ${figText(r.local)}`);
      }
      for (const a of o.extractor!.agreement) check(a.key, figText(a.fig));
    }
  });

  it("copy has no digits, never says safe, and keeps the honesty wording", () => {
    for (const lang of LANGS) {
      const text = Object.values(KPI_COPY[lang]).join(" ");
      expect(text.replaceAll("95%", "")).not.toMatch(/\d/);
      expect(text).not.toMatch(/\bsafe\b|آمن/i);
      expect(text).not.toMatch(/Abu Dhabi|أبوظبي|شرطة/);
    }
  });

  it("badges follow the artifact's own provenance text", () => {
    expect(badgeOf("synthetic fixtures (Falcon Demo Bank, reserved hosts); not real phishing", "REAL")).toBe("FIXTURE");
    expect(badgeOf("synthetic fixtures; cost depends on prompts", "REAL")).toBe("FIXTURE");
    expect(badgeOf("real (val/test URL items) + synthetic (fixture verdicts)", "FIXTURE")).toBe("MIXED");
    expect(badgeOf("synthetic, single-author, supervisor-audited", "REAL")).toBe("SYNTHETIC");
    expect(badgeOf("offline T1 + arbiter on URLs; real data only", "FIXTURE")).toBe("REAL");
    expect(badgeOf("nothing", "FIXTURE")).toBe("FIXTURE");
    for (const b of Object.values(BADGE_LABEL)) expect(b.en.length).toBeGreaterThan(3);
  });
});
