import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS, DEMO_NWS } from "@/lib/demo";
import { STAGE_BUDGET_MS, closeStages, enterStage, seconds, tierRows } from "@/lib/voice-progress";

describe("progress stages", () => {
  it("each stage closes the previous one with its own elapsed time", () => {
    let s = enterStage([], "heard", undefined, 1000);
    s = enterStage(s, "heard", "hello", 1500, 1000); // same stage: only the detail changes
    expect(s).toHaveLength(1);
    expect(s[0]).toMatchObject({ status: "active", detail: "hello", startedAt: 1000 });
    s = enterStage(s, "understand", "check", 3400);
    expect(s.map((x) => [x.id, x.status])).toEqual([["heard", "done"], ["understand", "active"]]);
    expect(s[0]!.ms).toBe(2400);
    s = closeStages(s, 4000);
    expect(s.every((x) => x.status === "done")).toBe(true);
    expect(s[1]!.ms).toBe(600);
  });
  it("formats seconds and has a budget for every stage", () => {
    expect(seconds(3240)).toBe("3.2");
    expect(seconds(-5)).toBe("0.0");
    for (const id of ["heard", "understand", "investigate", "link", "answer"] as const) expect(STAGE_BUDGET_MS[id]).toBeGreaterThan(1000);
  });
});

describe("tier rows come from the verdict, never invented", () => {
  it("lists only the tiers reached while running, and marks the rest skipped once final", () => {
    const running = tierRows(DEMO_NWS, "message", "en", false);
    const final = tierRows(DEMO_NWS, "message", "en", true);
    expect(running.every((r) => r.status === "done")).toBe(true);
    expect(final.length).toBeGreaterThanOrEqual(running.length);
    expect(final.filter((r) => r.status === "done").map((r) => r.tier)).toEqual(running.map((r) => r.tier));
    for (const r of final) if (r.status === "skipped") expect(r.found).toBeUndefined();
    expect(final.some((r) => r.tier === "T2")).toBe(false); // a message never visits a page
  });
  it("a link shows the page-visit tier", () => {
    expect(tierRows(DEMO_DANGEROUS, "url", "en", true).some((r) => r.tier === "T2")).toBe(true);
  });
  it("one short line per tier", () => {
    for (const r of tierRows(DEMO_DANGEROUS, "url", "ar", true)) if (r.found) expect(r.found.length).toBeLessThanOrEqual(240);
  });
});
