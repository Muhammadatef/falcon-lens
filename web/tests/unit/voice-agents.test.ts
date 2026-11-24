import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS, DEMO_NWS } from "@/lib/demo";
import { sentinelFindingClips } from "@/lib/voice-script";
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
  it("narrates only what the data proves: link/summary from the trace, draft/approval from the incident's actions", () => {
    const none = { drafted: false, awaiting: false };
    expect(sentinelSteps({ runs: [] }, none)).toEqual([]);
    expect(sentinelSteps({ runs: [{ steps: [{ node: "enrich" }, { node: "summarise" }] }] }, none)).toEqual(["linked", "summary"]);
    expect(sentinelSteps({ runs: [] }, { drafted: true, awaiting: true })).toEqual(["draft", "awaiting_approval"]);
    expect(sentinelSteps({ runs: [] }, { drafted: true, awaiting: false })).toEqual(["draft"]);
    expect(sentinelSteps({ runs: [{ steps: [{ node: "summarise" }] }] }, { drafted: false, awaiting: true })).toEqual(["summary"]);
  });
  it("reads drafted and awaiting from the incident's action mode and status", () => {
    const mk = (actions: unknown[]) => findIncident({ items: [{ incident_id: incId, linked_verdicts: ["vd_A"], actions }] }, ["vd_A"]);
    expect(mk([{ mode: "external_draft", status: "awaiting_approval" }])).toMatchObject({ drafted: true, awaiting: true });
    expect(mk([{ mode: "external_draft", status: "approved" }])).toMatchObject({ drafted: true, awaiting: false });
    expect(mk([{ mode: "internal_auto", status: "executed" }])).toMatchObject({ drafted: false, awaiting: false });
    expect(mk([{ mode: "external_draft", status: "rejected" }])).toMatchObject({ drafted: false });
  });
  it("spoken Sentinel lines come only from clips and only for facts", () => {
    expect(sentinelFindingClips({ linked: 3, linkStep: true, summary: true, drafted: true, awaiting: true })).toEqual(["sentinel.linked.3", "sentinel.summary", "sentinel.draft", "sentinel.awaiting_approval"]);
    expect(sentinelFindingClips({ linked: 1, linkStep: true, summary: false, drafted: false, awaiting: true })).toEqual([]);
    expect(sentinelFindingClips({ linked: 0, linkStep: false, summary: false, drafted: false, awaiting: false })).toEqual([]);
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
        expect(t).toContain(lang === "ar" ? "«بصير»" : "Investigator");
        expect(t).toContain(lang === "ar" ? "«درع»" : "Sentinel");
        expect(t.toLowerCase()).not.toMatch(/\bsafe(ly|r|st)?\b|آمن/);
      }
    }
  });
});
