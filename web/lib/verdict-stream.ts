/**
 * Check state machine. Pure: no DOM, no network (the hook in lib/use-check.ts drives it).
 * One `verdict` action per SSE `event: verdict`; each carries the whole Verdict so far.
 *
 * Rules encoded here (docs/DESIGN.md §2, IMPLEMENTATION_PLAN.md §3):
 *  - While `final=false` a provisional "suspicious" or "dangerous" may be shown, never a
 *    provisional "no warning signs".
 *  - Tiers: <= tier_reached are done; the next one is running until `final`; after
 *    `final` the remaining tiers are skipped.
 *  - Only evidence that was not in the previous event animates in.
 *  - A final verdict is terminal: later events for the same id are ignored.
 */
import { TIERS, type InputType, type Tier, type Verdict } from "./contracts";

export type TierStatus = "pending" | "running" | "done" | "skipped";
export type Phase = "idle" | "submitting" | "waiting" | "streaming" | "final" | "interrupted" | "failed";

export interface Problem {
  kind: "rate_limited" | "too_large" | "invalid" | "unsupported" | "not_found" | "unavailable" | "network";
  status: number;
  /** Seconds, from Retry-After, when the API sent one. */
  retryAfter?: number;
}

export interface CheckInputPreview {
  kind: InputType;
  /** What the person submitted, kept in memory only so the case header can echo it. */
  text: string;
}

export interface CheckState {
  phase: Phase;
  verdictId: string | null;
  verdict: Verdict | null;
  tiers: Record<Tier, TierStatus>;
  /** Evidence ids first seen in the latest event. */
  freshEvidenceIds: string[];
  provisional: "suspicious" | "dangerous" | null;
  events: number;
  /** The first event was already final (cached verdict): skip tier choreography. */
  singleEvent: boolean;
  problem: Problem | null;
  input: CheckInputPreview | null;
  /** True when the stream was played from built-in demo fixtures (?demo=1 only). */
  demo: boolean;
}

export type CheckAction =
  | { type: "submit"; input: CheckInputPreview }
  | { type: "accepted"; verdictId: string; demo?: boolean }
  | { type: "attach"; verdictId: string }
  | { type: "verdict"; verdict: Verdict }
  | { type: "interrupted" }
  | { type: "failed"; problem: Problem }
  | { type: "reset" };

const pendingTiers = (): Record<Tier, TierStatus> => ({ T0: "pending", T1: "pending", T2: "pending", T3: "pending" });

export const initialCheckState: CheckState = {
  phase: "idle",
  verdictId: null,
  verdict: null,
  tiers: pendingTiers(),
  freshEvidenceIds: [],
  provisional: null,
  events: 0,
  singleEvent: false,
  problem: null,
  input: null,
  demo: false,
};

export function tierStatus(v: Verdict | null, waiting = false): Record<Tier, TierStatus> {
  const reached = v ? TIERS.indexOf(v.tier_reached) : -1;
  const out = pendingTiers();
  TIERS.forEach((tier, i) => {
    if (i <= reached) out[tier] = "done";
    else if (v?.final) out[tier] = "skipped";
    else if (i === reached + 1 && (v || waiting)) out[tier] = "running";
  });
  return out;
}

export function checkReducer(state: CheckState, action: CheckAction): CheckState {
  switch (action.type) {
    case "reset":
      return initialCheckState;
    case "submit":
      return { ...initialCheckState, phase: "submitting", input: action.input };
    case "accepted":
      return { ...state, phase: "waiting", verdictId: action.verdictId, tiers: tierStatus(null, true), problem: null, demo: action.demo === true };
    case "attach":
      if (state.verdictId === action.verdictId) return state;
      return { ...initialCheckState, phase: "waiting", verdictId: action.verdictId, tiers: tierStatus(null, true) };
    case "verdict": {
      const v = action.verdict;
      if (state.verdictId !== null && v.verdict_id !== state.verdictId) return state;
      if (state.phase === "final") return state;
      const known = new Set(state.verdict?.evidence.map((e) => e.id) ?? []);
      return {
        ...state,
        phase: v.final ? "final" : "streaming",
        verdictId: v.verdict_id,
        verdict: v,
        tiers: tierStatus(v),
        freshEvidenceIds: v.evidence.filter((e) => !known.has(e.id)).map((e) => e.id),
        provisional: v.final || v.verdict === "no_warning_signs" ? null : v.verdict,
        events: state.events + 1,
        singleEvent: v.final && state.events === 0,
        problem: null,
      };
    }
    case "interrupted":
      if (state.phase === "final") return state;
      return { ...state, phase: "interrupted" };
    case "failed":
      if (state.phase === "final") return state;
      return { ...state, phase: "failed", problem: action.problem };
  }
}

export type LensState = "idle" | "scanning" | "locked";
export const lensStateFor = (phase: Phase): LensState =>
  phase === "final" ? "locked" : phase === "submitting" || phase === "waiting" || phase === "streaming" ? "scanning" : "idle";
