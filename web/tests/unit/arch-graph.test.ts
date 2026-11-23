import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { BIZ_GROUPS, FULL_GROUPS, NODES, NODE_BY_ID, idsOf, relatedOf } from "@/lib/arch-graph";
import { CAP_IDS } from "@/lib/capabilities";
import { DOC_SLUGS } from "@/lib/docs-content";
import { ARCH_UI, NODE_TEXT, TOOL_IO } from "@/lib/i18n-arch";
import { parseDspyRows, excludesZero } from "@/lib/dspy-results";
import generated from "@/lib/capabilities.generated.json";

const REPO = join(process.cwd(), "..");
const langs = ["en", "ar"] as const;
const tools = JSON.parse(readFileSync(join(REPO, "contracts", "tools.schema.json"), "utf8")) as Record<string, Record<string, unknown>>;

describe("architecture node data", () => {
  it("has unique ids and every node sits in a full-view group", () => {
    expect(new Set(NODES.map((n) => n.id)).size).toBe(NODES.length);
    const full = new Set(idsOf(FULL_GROUPS));
    const biz = new Set(idsOf(BIZ_GROUPS));
    for (const n of NODES) expect(full.has(n.id) || biz.has(n.id), n.id).toBe(true);
    for (const id of [...full, ...biz]) expect(NODE_BY_ID.has(id), id).toBe(true);
  });

  for (const lang of langs) {
    it(`every node has a tooltip pair (plain + technical), panel content in ${lang}`, () => {
      for (const n of NODES) {
        const t = NODE_TEXT[lang][n.id];
        expect(t, `${lang}:${n.id}`).toBeDefined();
        expect(t!.name.length, `${lang}:${n.id}.name`).toBeGreaterThan(2);
        for (const k of ["plain", "tech", "why", "never"] as const) expect(t![k].length, `${lang}:${n.id}.${k}`).toBeGreaterThan(8);
        if (!TOOL_IO[n.id]) {
          expect(t!.inputs.length, `${lang}:${n.id}.inputs`).toBeGreaterThan(3);
          expect(t!.outputs.length, `${lang}:${n.id}.outputs`).toBeGreaterThan(3);
        }
      }
    });
    it(`never says "safe" in ${lang}`, () => {
      const all = JSON.stringify([NODE_TEXT[lang], ARCH_UI[lang]]);
      expect(all).not.toMatch(/\bsafe\b|آمن/i);
    });
  }

  it("Arabic copy is Arabic (every plain sentence holds Arabic letters)", () => {
    for (const n of NODES) expect(NODE_TEXT.ar[n.id]!.plain, n.id).toMatch(/[؀-ۿ]/);
  });

  it("every repo path, extra path and docs file exists in the repository", () => {
    for (const n of NODES) {
      for (const p of [n.repo, ...(n.repoMore ?? []), n.docFile]) expect(existsSync(join(REPO, p)), `${n.id}: ${p}`).toBe(true);
      expect((DOC_SLUGS as readonly string[]).includes(n.doc), n.id).toBe(true);
    }
  });

  it("every node carries a known capability flag", () => {
    for (const n of NODES) expect(CAP_IDS.includes(n.cap), n.id).toBe(true);
  });

  it("every tool in contracts/tools.schema.json is a node, with matching mode", () => {
    for (const group of ["investigator_tools", "sentinel_tools"] as const) {
      for (const [name, spec] of Object.entries(tools[group]!)) {
        const node = NODE_BY_ID.get(name);
        expect(node, name).toBeDefined();
        expect(node!.group).toBe(group === "investigator_tools" ? "tools_inv" : "tools_sen");
        expect(TOOL_IO[name], name).toBeDefined();
        if (group === "sentinel_tools") expect(TOOL_IO[name]!.mode).toBe((spec as { mode: string }).mode);
      }
    }
    expect(NODES.filter((n) => n.group === "tools_inv")).toHaveLength(Object.keys(tools.investigator_tools!).length);
    expect(NODES.filter((n) => n.group === "tools_sen")).toHaveLength(Object.keys(tools.sentinel_tools!).length);
  });

  it("relations only point at real nodes and are symmetric", () => {
    for (const n of NODES) for (const r of relatedOf(n.id)) {
      expect(NODE_BY_ID.has(r), `${n.id} -> ${r}`).toBe(true);
      expect(relatedOf(r)).toContain(n.id);
    }
  });
});

describe("DSPy capability and results", () => {
  it("the dspy flag is live only with the loader and an adopted compiled file on the tree", () => {
    const dir = join(REPO, "packages", "falcon_core", "src", "falcon_core", "prompts", "compiled");
    const loader = existsSync(join(dir, "__init__.py"));
    const hasJson = loader && readdirSync(dir).some((f) => f.endsWith(".json"));
    expect((generated as Record<string, boolean>).dspy_compiled_prompts).toBe(hasJson);
  });
  it("shows no table without artifacts, and reads only recorded numbers", () => {
    expect(parseDspyRows([])).toEqual([]);
    expect(parseDspyRows(null)).toEqual([]);
    const rows = parseDspyRows([{ artifact: "a.json", role: "extractor", model: "m", synthetic: true, adopted: true, before: { mean: 0.5 }, after: { mean: 0.6 }, paired: { ci95: [-0.1, 0.3] } }]);
    expect(rows).toHaveLength(1);
    expect(excludesZero(rows[0]!)).toBe(false);
    expect(excludesZero({ ...rows[0]!, low: 0.01, high: 0.2 })).toBe(true);
  });
});
