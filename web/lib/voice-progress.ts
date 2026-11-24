/**
 * Live progress of one voice request, shown under the microphone: Heard you, Understanding, Baseer checks (with the
 * tiers that really ran, read from the verdict event stream), Dir links, Result. Pure state helpers, no DOM.
 * Nothing here invents a step or a delay: a stage appears when the code reaches it, a tier is "done" only when the
 * verdict says it ran and "skipped" only once the final verdict says it did not.
 */
import type { Lang, Verdict } from "./contracts";
import { newProgressSteps, type ProgressStep } from "./voice";
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

const STEP_TIER: Record<ProgressStep, TierId> = { lists: "T0", lookalike: "T1", wording: "T1", browser: "T2", ai: "T3" };
const ORDER: TierId[] = ["T0", "T1", "T2", "T3"];

/**
 * The tiers of the message being checked. A tier that ran is "done" with its strongest evidence line; once the final
 * verdict is in, a tier that did not run is shown as "skipped". While the check is running only reached tiers are listed.
 */
export function tierRows(v: Verdict, kind: "url" | "message", lang: Lang, final: boolean): TierRow[] {
  const ran = newProgressSteps(v, kind, new Set<ProgressStep>());
  const byTier = new Map<TierId, ProgressStep>(ran.map((s) => [STEP_TIER[s], s]));
  const rows: TierRow[] = [];
  for (const tier of ORDER) {
    if (tier === "T2" && kind !== "url" && !v.evidence.some((e) => e.tier === "T2")) continue;
    const step = byTier.get(tier);
    if (step) rows.push({ tier, step, status: "done", found: tierFoundText(lang, step, v) });
    else if (final) rows.push({ tier, step: tier === "T0" ? "lists" : tier === "T1" ? (kind === "url" ? "lookalike" : "wording") : tier === "T2" ? "browser" : "ai", status: "skipped" });
  }
  return rows;
}

/** "3.2" for 3240 ms. */
export const seconds = (ms: number): string => (Math.max(0, ms) / 1000).toFixed(1);
