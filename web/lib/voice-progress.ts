/**
 * Live progress of one voice request, shown under the microphone: Heard you, Understanding, Baseer checks (with the
 * tiers that really ran, read from the verdict event stream), Dir links, Result. Pure state helpers, no DOM.
 * Nothing here invents a step or a delay: a stage appears when the code reaches it, a tier is "done" only when the
 * verdict says it ran and "skipped" only once the final verdict says it did not.
 */
import type { Lang, Verdict } from "./contracts";
import type { ProgressStep } from "./voice";
import { tierFoundText } from "./voice-speech";

export type StageId = "heard" | "understand" | "investigate" | "link" | "answer" | "reply";
export interface Stage {
  id: StageId;
  status: "active" | "done";
  /** One short line (the transcript, the intent, "message 2 of 3"). */
  detail?: string;
  startedAt: number;
  /** Elapsed time once the stage is done. */
  ms?: number;
}

/** After this long in one stage the panel says "Still checking…" instead of staying silent. */
export const STAGE_BUDGET_MS: Record<StageId, number> = { heard: 6000, understand: 3000, investigate: 12000, link: 15000, answer: 8000, reply: 8000 };

const closeActive = (stages: readonly Stage[], now: number): Stage[] => stages.map((s) => (s.status === "active" ? { ...s, status: "done" as const, ms: Math.max(0, now - s.startedAt) } : s));

/** Starts a stage (closing the active one). Entering a stage that is already there only updates its detail. */
export function enterStage(stages: readonly Stage[], id: StageId, detail: string | undefined, now: number, startedAt = now): Stage[] {
  const have = stages.find((s) => s.id === id);
  if (have) return stages.map((s) => (s.id === id ? { ...s, detail: detail ?? s.detail } : s));
  return [...closeActive(stages, now), { id, status: "active", detail, startedAt }];
}

export const closeStages = (stages: readonly Stage[], now: number): Stage[] => closeActive(stages, now);

export type TierId = "T0" | "T1" | "T2" | "T3";
export interface TierRow {
  tier: TierId;
  step: ProgressStep;
  status: "done" | "skipped";
  /** What this check found at the tier: exactly the finding lines that are spoken (see voice-speech stepGroups). */
  found?: string;
}

const ORDER: TierId[] = ["T0", "T1", "T2", "T3"];

/**
 * The tiers of the message being checked. A tier that ran is "done" with its strongest evidence line; once the final
 * verdict is in, a tier that did not run is shown as "skipped". While the check is running only reached tiers are listed.
 */
export function tierRows(v: Verdict, kind: "url" | "message", lang: Lang, final: boolean): TierRow[] {
  const rows: TierRow[] = [];
  for (const tier of ORDER) {
    const step: ProgressStep = tier === "T0" ? "lists" : tier === "T1" ? (kind === "url" ? "lookalike" : "wording") : tier === "T2" ? "browser" : "ai";
    // A tier that ran says what THIS check found there (or "nothing notable at this layer"), never "skipped".
    if (tierRan(v, tier)) rows.push({ tier, step, status: "done", found: tierFoundText(lang, step, v) });
    else if (tier === "T2" && kind !== "url") continue; // a message without a link never visits a page
    else if (final) rows.push({ tier, step, status: "skipped" });
  }
  return rows;
}

/** A tier ran when the verdict reached it AND it left evidence or a trace step (T3: the model call), even if it found nothing. */
export function tierRan(v: Verdict, tier: TierId): boolean {
  if (tier === "T0") return true;
  if (RANK[v.tier_reached] < RANK[tier]) return false;
  if (v.evidence.some((e) => e.tier === tier)) return true;
  const trace = v.trace ?? [];
  if (tier === "T3") return trace.some((s) => s.kind === "llm");
  return trace.some((s) => s.kind === "tier" && `${s.name ?? ""} ${s.summary}`.includes(tier));
}

const RANK = { T0: 0, T1: 1, T2: 2, T3: 3 } as const;

/** "3.2" for 3240 ms. */
export const seconds = (ms: number): string => (Math.max(0, ms) / 1000).toFixed(1);
