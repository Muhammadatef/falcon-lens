import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { FLOWS, FLOW_UI, GRAPH_BADGE, MAIN_FLOW, NODE_DESC, badgeTool, nodesOf, type Badge } from "@/lib/arch-flow";
import { NODE_BY_ID } from "@/lib/arch-graph";
import { CAP_IDS } from "@/lib/capabilities";
import { LOGO_PATHS } from "@/lib/tool-logos.gen";

const REPO = join(process.cwd(), "..");
const read = (path: string) => readFileSync(join(REPO, path), "utf8");
const ARABIC = /[؀-ۿ]/;
const ICON_SOURCE = read("web/components/Icon.tsx");

function checkBadge(badge: Badge, where: string) {
  if ("logo" in badge) expect(LOGO_PATHS[badge.logo], `${where}: logo ${badge.logo}`).toBeDefined();
  else if ("mono" in badge) {
    expect(badge.mono.length, `${where}: text badge`).toBeGreaterThan(0);
    expect(badge.mono.length, `${where}: text badge`).toBeLessThanOrEqual(4);
    expect(badge.tool.length, `${where}: tool name`).toBeGreaterThan(2);
  } else expect(ICON_SOURCE, `${where}: icon ${badge.icon}`).toContain(`  ${badge.icon}: [`);
}

describe("animated architecture diagrams: structure", () => {
  it("has the five diagrams, the main one in three layers", () => {
    expect(FLOWS.map((f) => f.id)).toEqual(["main", "baseer", "dir", "dspy", "route"]);
    expect(MAIN_FLOW.bands.map((b) => b.id)).toEqual(["voice", "agents", "platform"]);
    expect(MAIN_FLOW.bands[1]!.groups.map((g) => g.id)).toEqual(["baseer", "dir"]);
  });

  for (const spec of FLOWS) {
    const nodes = nodesOf(spec);
    describe(spec.id, () => {
      it("every node has a logo or a badge, and a label and a line in Arabic and English", () => {
        expect(new Set(nodes.map((n) => n.id)).size).toBe(nodes.length);
        for (const n of nodes) {
          checkBadge(n.badge, `${spec.id}.${n.id}`);
          for (const lang of ["en", "ar"] as const) {
            expect(n.label[lang].trim().length, `${n.id}.label.${lang}`).toBeGreaterThan(2);
            expect(n.sub[lang].trim().length, `${n.id}.sub.${lang}`).toBeGreaterThan(3);
          }
          expect(n.sub.ar, `${n.id}.sub.ar`).toMatch(ARABIC);
        }
      });

      it("every node names shipped code, a real capability flag and a detail text", () => {
        for (const n of nodes) {
          expect(existsSync(join(REPO, n.repo)), `${n.id}: ${n.repo}`).toBe(true);
          expect(CAP_IDS, `${n.id}: ${n.cap}`).toContain(n.cap);
          if (n.graph) expect(NODE_BY_ID.has(n.graph), `${n.id} -> ${n.graph}`).toBe(true);
          else {
            const d = NODE_DESC[n.id];
            expect(d, `${n.id}: needs a graph node or a description`).toBeDefined();
            expect(d!.en.length).toBeGreaterThan(40);
            expect(d!.ar).toMatch(ARABIC);
          }
        }
      });

      it("the request path visits existing nodes once, with a caption in both languages", () => {
        const ids = new Set(nodes.map((n) => n.id));
        expect(spec.steps.length).toBeGreaterThanOrEqual(6);
        expect(new Set(spec.steps.map((s) => s.node)).size).toBe(spec.steps.length);
        for (const s of spec.steps) {
          expect(ids.has(s.node), s.node).toBe(true);
          expect(s.caption.en.length, s.node).toBeGreaterThan(20);
          expect(s.caption.ar, s.node).toMatch(ARABIC);
        }
        for (const text of [spec.title, spec.lead, ...spec.bands.flatMap((b) => [b.title, b.sub, ...b.groups.flatMap((g) => (g.title ? [g.title] : []))])]) {
          expect(text.en.trim().length).toBeGreaterThan(2);
          expect(text.ar.trim().length).toBeGreaterThan(2);
        }
        for (const g of spec.bands.flatMap((b) => b.groups)) if (g.badge) checkBadge(g.badge, `${spec.id}.${g.id}`);
      });
    });
  }

  it("the main request path is the one the owner asked for", () => {
    expect(MAIN_FLOW.steps.map((s) => s.node)).toEqual(["v_mic", "v_stt", "v_intent", "t0", "t1", "t2", "t3", "arbiter", "verdict", "p_redis", "s_correlate", "s_rules", "s_graph", "s_incident", "s_approval"]);
  });

  it("lane-diagram badges point at real nodes", () => {
    for (const [id, badge] of Object.entries(GRAPH_BADGE)) {
      expect(NODE_BY_ID.has(id), id).toBe(true);
      checkBadge(badge, `graph.${id}`);
    }
  });

  it("the player words exist in both languages", () => {
    expect(Object.keys(FLOW_UI.ar).sort()).toEqual(Object.keys(FLOW_UI.en).sort());
    for (const v of Object.values(FLOW_UI.ar)) expect(v).toMatch(ARABIC);
    expect(FLOW_UI.en.logos).toBe("Logos belong to their owners; shown to identify the tools used.");
  });
});

describe("animated architecture diagrams: wording and truthfulness", () => {
  const all = JSON.stringify([FLOWS, NODE_DESC, FLOW_UI]);

  it("keeps the product wording rules", () => {
    expect(all).not.toMatch(/\bsafe\b|آمن|خطير(?!ة)/);
    expect(all).not.toMatch(/Abu Dhabi Police|\bADP\b|شرطة/);
    expect(all).not.toMatch(/ADR-\d{3}/);
    expect(all).toContain("«بصير»، المحقّق");
    expect(all).toContain("«درع»، الحارس");
    expect(all).toMatch(/Ready to connect; not connected/);
  });

  /** A tool appears only if the repository really uses it: each name maps to a file and a string found in it. */
  const EVIDENCE: Record<string, [string, RegExp]> = {
    FastAPI: ["packages/falcon_core/pyproject.toml", /"fastapi>=/],
    Redis: ["docker-compose.yml", /image: redis:/],
    PostgreSQL: ["docker-compose.yml", /pgvector\/pgvector:[\w.-]*pg\d+/],
    Docker: ["docker-compose.yml", /services:/],
    Caddy: ["docker-compose.yml", /image: caddy:/],
    Cloudflare: ["Makefile", /cloudflared/],
    Prometheus: ["docker-compose.yml", /image: prom\/prometheus:/],
    Grafana: ["docker-compose.yml", /image: grafana\/grafana:/],
    OpenTelemetry: ["packages/falcon_core/pyproject.toml", /opentelemetry-sdk/],
    LangGraph: ["services/sentinel/pyproject.toml", /langgraph==/],
    Ollama: ["packages/falcon_core/src/falcon_core/llm/config.py", /ollama/i],
    Claude: ["packages/falcon_core/pyproject.toml", /anthropic/],
    "Model Context Protocol": ["services/mcp/pyproject.toml", /"mcp[>=]/],
    QWen: ["packages/falcon_core/src/falcon_core/llm/config.py", /qwen/],
    "scikit-learn": ["services/worker/pyproject.toml", /scikit-learn/],
    "Next.js": ["web/package.json", /"next":/],
    Whisper: ["services/voice-native/pyproject.toml", /mlx-whisper==/],
    "Amazon Polly": ["tools/voice_clips/src/voice_clips/engines.py", /polly/i],
    Kokoro: ["tools/voice_clips/src/voice_clips/engines.py", /kokoro/i],
    Playwright: ["services/sandbox/pyproject.toml", /playwright==/],
    pgvector: ["docker-compose.yml", /pgvector\/pgvector:/],
    "Arize Phoenix": ["docker-compose.yml", /image: arizephoenix\/phoenix:/],
    "Grafana Loki": ["docker-compose.yml", /loki/],
    Alertmanager: ["docker-compose.yml", /image: prom\/alertmanager:/],
    DSPy: ["evals/dspy/optimize.py", /dspy/],
    Inkling: ["packages/falcon_core/src/falcon_core/llm/config.py", /inkling/],
    "STIX 2.1": ["packages/falcon_core/src/falcon_core/tools/stix.py", /stix/i],
  };

  it("shows only tools the shipped code uses", () => {
    const shown = new Set<string>();
    for (const spec of FLOWS) {
      for (const n of nodesOf(spec)) {
        const tool = badgeTool(n.badge, LOGO_PATHS);
        if (tool) shown.add(tool);
      }
      for (const g of spec.bands.flatMap((b) => b.groups)) {
        const tool = g.badge ? badgeTool(g.badge, LOGO_PATHS) : null;
        if (tool) shown.add(tool);
      }
    }
    for (const tool of shown) {
      const proof = EVIDENCE[tool];
      expect(proof, `no evidence rule for ${tool}`).toBeDefined();
      expect(read(proof![0]), `${tool}: ${proof![0]}`).toMatch(proof![1]);
    }
    // Every vendored logo is used by at least one diagram (nothing is shipped for decoration).
    for (const logo of Object.values(LOGO_PATHS)) expect(shown.has(logo.title), `unused logo ${logo.title}`).toBe(true);
  });

  it("the DSPy nodes carry the capability flag that is In progress until compiled prompts ship", () => {
    const dspy = FLOWS.flatMap(nodesOf).filter((n) => "mono" in n.badge && n.badge.tool === "DSPy");
    expect(dspy.length).toBeGreaterThan(1);
    for (const n of dspy) expect(n.cap).toBe("dspy_compiled_prompts");
  });
});
