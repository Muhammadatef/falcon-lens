import { describe, expect, it } from "vitest";
import { BUILDING_AGENTS, type BuildingAgentsCopy } from "@/lib/docs-building-agents";
import { DOC_SLUGS } from "@/lib/docs-content";
import { bundledDspyRows } from "@/lib/dspy-results";

function strings(c: BuildingAgentsCopy): string[] {
  const out: string[] = [c.lead, ...Object.values(c.legend)];
  const items = (xs: { title: string; body: string }[]) => xs.flatMap((i) => [i.title, i.body]);
  out.push(c.process.title, c.process.intro, ...items(c.process.items));
  for (const k of ["sentinel", "dspy"] as const) {
    out.push(c[k].title, c[k].intro, c[k].label, ...items(c[k].notes));
    for (const l of c[k].lanes) out.push(l.title, ...l.nodes.flatMap((n) => [n.name, n.note]));
  }
  out.push(c.whyLg.title, c.whyLg.intro, ...items(c.whyLg.items), c.whyLg.coreTitle, c.whyLg.core, c.whyLg.invTitle, c.whyLg.inv);
  const d = c.whyDspy;
  out.push(d.title, d.intro, ...items(d.items), d.resultTitle, d.result, d.none, d.tableCaption, ...d.cols, d.gateTitle, d.gate);
  out.push(c.notUsed.title, c.notUsed.intro, ...items(c.notUsed.items), c.back);
  return out;
}

describe("/docs/building-agents copy", () => {
  it("is a registered docs slug", () => {
    expect(DOC_SLUGS).toContain("building-agents");
  });

  it("has the same structure in Arabic and English", () => {
    const shape = (c: BuildingAgentsCopy) => ({
      p: c.process.items.length,
      s: c.sentinel.lanes.map((l) => l.nodes.map((n) => n.id)),
      d: c.dspy.lanes.map((l) => l.nodes.map((n) => n.id)),
      lg: c.whyLg.items.length,
      wd: c.whyDspy.items.length,
      nu: c.notUsed.items.length,
    });
    expect(shape(BUILDING_AGENTS.ar)).toEqual(shape(BUILDING_AGENTS.en));
  });

  it("says no 'safe', no internal labels, no digits typed, no endorsement", () => {
    for (const lang of ["ar", "en"] as const) {
      const all = strings(BUILDING_AGENTS[lang]).join("\n");
      expect(all.toLowerCase(), lang).not.toMatch(/\bsafe(ly|r|st)?\b/);
      expect(all, lang).not.toContain("آمن");
      expect(all, lang).not.toMatch(/ADR-\d|PR #\d|#\d{2,}/);
      expect(all, lang).not.toMatch(/endorsed|مؤيَّد|integrated with abu dhabi/i);
      // Counts are written in words; the only digits allowed are the 95 of the paired interval.
      expect(all.replace(/95\s?[%٪]|MIPROv2/g, ""), lang).not.toMatch(/\d/);
    }
  });

  it("the DSPy result is read from the artifacts: this tree adopted nothing", () => {
    const rows = bundledDspyRows();
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.every((r) => !r.adopted)).toBe(true);
  });
});
