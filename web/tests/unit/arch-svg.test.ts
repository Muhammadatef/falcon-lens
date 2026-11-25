import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FLOW_UI, MAIN_FLOW, nodesOf } from "@/lib/arch-flow";
import generated from "@/lib/capabilities.generated.json";

const REPO = join(process.cwd(), "..");
const svg = readFileSync(join(REPO, "docs", "assets", "architecture.svg"), "utf8");

describe("README architecture figure (docs/assets/architecture.svg)", () => {
  it("is the current output of scripts/build-arch-svg.mjs", () => {
    const out = execFileSync(process.execPath, ["scripts/build-arch-svg.mjs", "--check"], { cwd: process.cwd(), encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    expect(out).toContain("up to date");
  });

  it("names the three layers, shows a logo or a badge for every box, and carries the logo footnote", () => {
    for (const band of MAIN_FLOW.bands) {
      expect(svg).toContain(band.title.en.replace(/"/g, "&quot;"));
      expect(svg).toContain(band.title.ar);
    }
    expect((svg.match(/<rect class="n(?: on d\d+)?"/g) ?? []).length).toBe(nodesOf(MAIN_FLOW).length);
    expect((svg.match(/<g class="no d\d+">/g) ?? []).length).toBe(MAIN_FLOW.steps.length);
    expect(svg).toContain(FLOW_UI.en.logos);
    expect(svg).toContain("<animateMotion");
    expect(svg).toContain("prefers-reduced-motion:reduce");
  });

  it("is self-contained and honest: no script, no external reference, no police mark, In progress where the flag says so", () => {
    expect(svg).not.toMatch(/<script|<image|href=|<foreignObject|url\(/i);
    expect(svg).not.toMatch(/Abu Dhabi Police|شرطة|\bsafe\b|آمن/);
    const pending = nodesOf(MAIN_FLOW).filter((n) => (generated as Record<string, boolean>)[n.cap] !== true);
    expect((svg.match(/>In progress</g) ?? []).length).toBe(pending.length);
  });
});
