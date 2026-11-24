import { describe, expect, it } from "vitest";
import { hostOnly, parseSummary, upsertSummary, type VerdictSummary } from "../../lib/history";
import { HISTORY_MESSAGES } from "../../lib/i18n-history";

const raw = (patch: Record<string, unknown> = {}) => ({
  verdict_id: "vd_01KB0DEM0DATA0000000000001",
  created_at: "2026-11-24T10:00:00Z",
  input_type: "url",
  display: "hxxps://falcon-demo-bank-secure[.]test",
  verdict: "dangerous",
  risk_score: 97,
  degraded: false,
  degraded_reasons: ["sandbox_timeout", "<img src=x onerror=alert(1)>"],
  tier_reached: "T2",
  model_route: "none",
  source: "synthetic",
  agent: { tiers_run: ["T0", "T1", "T2"], extractor_ran: false, investigator_ran: false, tool_calls: 2, llm_calls: 0 },
  ...patch,
});

describe("parseSummary", () => {
  it("accepts a valid summary and drops reason codes that are not codes", () => {
    const s = parseSummary(raw())!;
    expect(s.verdict_id).toBe("vd_01KB0DEM0DATA0000000000001");
    expect(s.degraded_reasons).toEqual(["sandbox_timeout"]);
    expect(s.agent.tool_calls).toBe(2);
  });
  it("rejects malformed ids, verdicts and tiers", () => {
    expect(parseSummary(raw({ verdict_id: "vd_x" }))).toBeNull();
    expect(parseSummary(raw({ verdict: "safe" }))).toBeNull();
    expect(parseSummary(raw({ tier_reached: "T9" }))).toBeNull();
    expect(parseSummary(null)).toBeNull();
  });
  it("never shows a degraded check as no warning signs", () => {
    expect(parseSummary(raw({ verdict: "no_warning_signs", degraded: true }))!.verdict).toBe("suspicious");
  });
  it("clamps the risk score and defaults unknown routes", () => {
    const s = parseSummary(raw({ risk_score: 900, model_route: "x" }))!;
    expect(s.risk_score).toBe(100);
    expect(s.model_route).toBe("none");
  });
});

describe("hostOnly", () => {
  it("drops userinfo, port, path and query", () => {
    expect(hostOnly("hxxps://admin:pw@falcon-demo[.]test:8443/login?t=SECRET")).toBe("hxxps://falcon-demo[.]test");
    expect(hostOnly("https://a.b/c")).toBe("hxxps://a[.]b");
    expect(hostOnly("javascript:alert(1)")).toBeNull();
    expect(hostOnly(null)).toBeNull();
  });
});

describe("upsertSummary", () => {
  it("replaces a known check and keeps newest first", () => {
    const a = parseSummary(raw())! as VerdictSummary;
    const b = parseSummary(raw({ verdict_id: "vd_01KB0DEM0DATA0000000000003", created_at: "2026-11-24T11:00:00Z" }))!;
    const out = upsertSummary(upsertSummary([a], b), { ...a, risk_score: 50 });
    expect(out.map((s) => s.verdict_id)).toEqual([b.verdict_id, a.verdict_id]);
    expect(out).toHaveLength(2);
    expect(out.find((s) => s.verdict_id === a.verdict_id)!.risk_score).toBe(50);
  });
});

describe("history strings", () => {
  it("have the same keys in both languages and never say safe", () => {
    expect(Object.keys(HISTORY_MESSAGES.ar).sort()).toEqual(Object.keys(HISTORY_MESSAGES.en).sort());
    for (const text of Object.values(HISTORY_MESSAGES.ar)) expect(text).not.toMatch(/آمن/);
    for (const text of Object.values(HISTORY_MESSAGES.en)) expect(text).not.toMatch(/\bsafe(ly|ty)?\b/i);
  });
});
