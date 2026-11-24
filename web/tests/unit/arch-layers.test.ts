import { existsSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LAYERS, LAYERS_UI, LAYER_LINKS } from "@/lib/arch-layers";

const REPO = join(__dirname, "../../..");
const steps = LAYERS.flatMap((l) => l.groups.flatMap((g) => g.steps));

describe("three-layer architecture content", () => {
  it("has the three layers in order: voice, agents, platform", () => {
    expect(LAYERS.map((l) => l.id)).toEqual(["voice", "agents", "platform"]);
    expect(LAYERS[1]!.groups.map((g) => g.id)).toEqual(["baseer", "dir"]);
    expect(LAYER_LINKS.map((l) => l.after)).toEqual(["voice", "agents"]);
  });

  it("every step names a path that exists in the repository (shipped code only)", () => {
    for (const s of steps) expect(existsSync(join(REPO, s.repo)), `${s.id}: ${s.repo}`).toBe(true);
  });

  it("Arabic and English are both present for every layer, group, step and link", () => {
    const pairs = [...LAYERS, ...LAYERS.flatMap((l) => l.groups), ...steps];
    for (const p of pairs) {
      for (const lang of ["ar", "en"] as const) {
        expect(p[lang].t.trim().length, p.id).toBeGreaterThan(2);
        expect(p[lang].d.trim().length, p.id).toBeGreaterThan(10);
      }
      expect(p.ar.t, p.id).toMatch(/[\u0600-\u06FF]/);
    }
    for (const l of LAYER_LINKS) expect(l.ar.length > 10 && l.en.length > 10).toBe(true);
    expect(Object.keys(LAYERS_UI.ar).sort()).toEqual(Object.keys(LAYERS_UI.en).sort());
  });

  it("uses the agreed names and wording, and no internal references", () => {
    const all = JSON.stringify(LAYERS.map((l) => [l.ar, l.en, l.groups.map((g) => [g.ar, g.en, g.steps.map((s) => [s.ar, s.en])])])) + JSON.stringify(LAYER_LINKS);
    expect(all).toContain("«بصير»، المحقّق");
    expect(all).toContain("«درع»، الحارس");
    expect(all).toContain("Baseer, the Investigator");
    expect(all).toContain("Dir', the Sentinel");
    expect(all).toContain("خطِر");
    expect(all).toMatch(/Ready to connect[^.]*; not connected/);
    expect(all).not.toMatch(/ADR-\d{3}|\bsafe\b|آمن|خطير|\.py\b|\.schema\.json|docs\/[A-Z]/);
  });
});
