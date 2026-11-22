import { describe, expect, it } from "vitest";
import { DEMO_DANGEROUS, DEMO_NWS, DEMO_STREAMS } from "@/lib/demo";
import { checkReducer, initialCheckState, lensStateFor, tierStatus, type CheckState } from "@/lib/verdict-stream";

const accepted = (id: string): CheckState =>
  checkReducer(checkReducer(initialCheckState, { type: "submit", input: { kind: "url", text: "x" } }), { type: "accepted", verdictId: id });

const play = (state: CheckState, scene: "danger" | "nws", upTo?: number): CheckState =>
  DEMO_STREAMS[scene].slice(0, upTo).reduce((s, step) => checkReducer(s, { type: "verdict", verdict: step.verdict }), state);

describe("tierStatus", () => {
  it("marks nothing before submission and T0 running while waiting", () => {
    expect(tierStatus(null)).toEqual({ T0: "pending", T1: "pending", T2: "pending", T3: "pending" });
    expect(tierStatus(null, true)).toEqual({ T0: "running", T1: "pending", T2: "pending", T3: "pending" });
  });
  it("runs the next tier while not final and skips the rest once final", () => {
    const partial = DEMO_STREAMS.danger[1]!.verdict;
    expect(tierStatus(partial)).toEqual({ T0: "done", T1: "done", T2: "running", T3: "pending" });
    expect(tierStatus(DEMO_DANGEROUS)).toEqual({ T0: "done", T1: "done", T2: "done", T3: "skipped" });
    expect(tierStatus(DEMO_NWS)).toEqual({ T0: "done", T1: "done", T2: "skipped", T3: "skipped" });
  });
});

describe("checkReducer", () => {
  it("goes submit → waiting → streaming → final across a dangerous stream", () => {
    let s = accepted(DEMO_DANGEROUS.verdict_id);
    expect(s.phase).toBe("waiting");
    expect(lensStateFor(s.phase)).toBe("scanning");

    s = play(s, "danger", 1);
    expect(s.phase).toBe("streaming");
    expect(s.freshEvidenceIds).toEqual(["ev_rep0feed01"]);

    s = play(s, "danger", 2);
    expect(s.events).toBe(3); // T0 again (ignored as duplicate evidence) + T1
    s = play(accepted(DEMO_DANGEROUS.verdict_id), "danger");
    expect(s.phase).toBe("final");
    expect(s.verdict?.verdict).toBe("dangerous");
    expect(s.provisional).toBeNull();
    expect(s.singleEvent).toBe(false);
    expect(lensStateFor(s.phase)).toBe("locked");
  });

  it("never shows a provisional no_warning_signs, but does show provisional suspicious", () => {
    let s = play(accepted(DEMO_DANGEROUS.verdict_id), "danger", 1);
    expect(s.verdict?.verdict).toBe("no_warning_signs");
    expect(s.verdict?.final).toBe(false);
    expect(s.provisional).toBeNull();
    s = play(accepted(DEMO_DANGEROUS.verdict_id), "danger", 2);
    expect(s.provisional).toBe("suspicious");
  });

  it("reports only evidence that is new in the latest event", () => {
    const s = play(accepted(DEMO_DANGEROUS.verdict_id), "danger", 2);
    expect(s.freshEvidenceIds).toEqual(["ev_url0combo1", "ev_dom0age001", "ev_dom0cert01"]);
    const again = checkReducer(s, { type: "verdict", verdict: s.verdict! });
    expect(again.freshEvidenceIds).toEqual([]);
  });

  it("flags a cached verdict that arrives as a single final event", () => {
    const s = checkReducer(accepted(DEMO_NWS.verdict_id), { type: "verdict", verdict: DEMO_NWS });
    expect(s.phase).toBe("final");
    expect(s.singleEvent).toBe(true);
  });

  it("ignores events for another verdict id and anything after final", () => {
    const waiting = accepted(DEMO_DANGEROUS.verdict_id);
    expect(checkReducer(waiting, { type: "verdict", verdict: DEMO_NWS })).toBe(waiting);

    const done = play(waiting, "danger");
    const late = { ...DEMO_DANGEROUS, verdict: "no_warning_signs" as const, risk_score: 1 };
    expect(checkReducer(done, { type: "verdict", verdict: late })).toBe(done);
    expect(checkReducer(done, { type: "interrupted" })).toBe(done);
    expect(checkReducer(done, { type: "failed", problem: { kind: "network", status: 0 } })).toBe(done);
  });

  it("keeps the last partial verdict when the stream is interrupted", () => {
    const s = checkReducer(play(accepted(DEMO_DANGEROUS.verdict_id), "danger", 2), { type: "interrupted" });
    expect(s.phase).toBe("interrupted");
    expect(s.verdict?.evidence.length).toBe(4);
    expect(lensStateFor(s.phase)).toBe("idle");
  });

  it("records a problem on failure and clears everything on a new submit", () => {
    const failed = checkReducer(accepted(DEMO_DANGEROUS.verdict_id), { type: "failed", problem: { kind: "rate_limited", status: 429, retryAfter: 30 } });
    expect(failed.phase).toBe("failed");
    expect(failed.problem?.retryAfter).toBe(30);
    const next = checkReducer(failed, { type: "submit", input: { kind: "message", text: "hello" } });
    expect(next.problem).toBeNull();
    expect(next.verdict).toBeNull();
    expect(next.phase).toBe("submitting");
  });

  it("attaches to an id from the URL and marks demo runs", () => {
    const attached = checkReducer(initialCheckState, { type: "attach", verdictId: DEMO_NWS.verdict_id });
    expect(attached.phase).toBe("waiting");
    expect(attached.tiers.T0).toBe("running");
    expect(checkReducer(attached, { type: "attach", verdictId: DEMO_NWS.verdict_id })).toBe(attached);
    expect(checkReducer(initialCheckState, { type: "accepted", verdictId: "x", demo: true }).demo).toBe(true);
    expect(checkReducer(attached, { type: "reset" })).toBe(initialCheckState);
  });
});
