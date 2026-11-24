import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS, DEMO_NWS } from "@/lib/demo";
import { aiStepText, buildSpeech, findIncident, narResult, sentinelSteps, type Outcome } from "@/lib/voice";

const d: Outcome = { id: "vd_a", verdict: DEMO_DANGEROUS };
const c: Outcome = { id: "vd_b", verdict: DEMO_NWS };
const incId = `inc_${"0".repeat(26)}`;

describe("agents: Investigator and Sentinel hand-over", () => {
  it("finds only an incident that links one of our verdict ids", () => {
    const list = { items: [{ incident_id: incId, severity: "high", linked_verdicts: ["vd_A", "vd_B"], summary: { en: "x" } }] };
    expect(findIncident(list, ["vd_B"])).toMatchObject({ id: incId, severity: "high", linked: 2 });
    expect(findIncident(list, ["vd_Z"])).toBeNull();
    expect(findIncident({ items: [{ incident_id: "bad", linked_verdicts: ["vd_A"] }] }, ["vd_A"])).toBeNull();
    expect(findIncident(null, ["vd_A"])).toBeNull();
  });
  it("narrates only the trace nodes that exist", () => {
    expect(sentinelSteps({ runs: [] })).toEqual([]);
    expect(sentinelSteps({ runs: [{ steps: [{ node: "enrich", tools: [] }, { node: "summarise", tools: [] }], interrupt: null }] })).toEqual(["linked", "summary"]);
    expect(sentinelSteps({ runs: [{ steps: [{ node: "propose", tools: [{ mode: "external_draft" }] }], interrupt: { action_id: "a", decision: null } }] })).toEqual(["draft", "awaiting_approval"]);
    expect(sentinelSteps({ runs: [{ steps: [], interrupt: { action_id: "a", decision: "approved" } }] })).toEqual([]);
  });
  it("names a model only when one answered, and credits the arbiter for the verdict", () => {
    expect(aiStepText("en", { ...DEMO_DANGEROUS, model_route: "none" })).toBeNull();
    expect(aiStepText("en", { ...DEMO_DANGEROUS, model_route: "local" })).toContain("local model");
    expect(aiStepText("en", { ...DEMO_DANGEROUS, model_route: "cloud" })).toContain("cloud model");
    expect(narResult("en", 1, DEMO_DANGEROUS)).toBe("The arbiter decided: the first message is dangerous.");
    expect(narResult("ar", 2, DEMO_NWS)).toContain("المحكّم");
  });
  it("the final speech names both agents and never says safe", () => {
    for (const lang of ["ar", "en"] as const) {
      for (const sentinelFound of [true, false]) {
        const t = buildSpeech(lang, [d, c], { sentinelFound });
        expect(t).toContain(lang === "ar" ? "«المحقّق»" : "Investigator");
        expect(t).toContain(lang === "ar" ? "«الحارس»" : "Sentinel");
        expect(t.toLowerCase()).not.toMatch(/\bsafe(ly|r|st)?\b|آمن/);
      }
    }
  });
});
