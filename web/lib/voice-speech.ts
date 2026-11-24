/**
 * Spoken output of the voice assistant (Emirati Arabic / English), composed ONLY from lib/voice-script.ts clips.
 * Screen text is separate (lib/i18n-voice.ts, formal Arabic). Nothing here invents a line: every utterance is a
 * concatenation of pre-recordable clip keys.
 */
import type { Lang, Verdict } from "./contracts";
import { countOutcomes, type Outcome, type ProgressStep } from "./voice";
import {
  arbiterClips,
  checkingClips,
  finalClips,
  sentinelFindingGroups,
  tierFindingGroups,
  type SentinelFinding,
  foundClips,
  investigatorStartClips,
  investigatorStepClips,
  render,
  toVoiceLang,
  type InvestigatorStep,
} from "./voice-script";

/** Renders clip keys in the spoken language (ar: Emirati). */
export const spoken = (lang: Lang, keys: readonly string[]): string => render(toVoiceLang(lang), keys);

/** Registry id of the brand named by the largest group of dangerous verdicts; null when there is none. */
export function campaignBrand(outcomes: readonly Outcome[]): string | null {
  const byBrand = new Map<string, number>();
  for (const o of outcomes) {
    const id = o.verdict?.verdict === "dangerous" ? o.verdict.impersonated_brand?.brand_id : undefined;
    if (id) byBrand.set(id, (byBrand.get(id) ?? 0) + 1);
  }
  return [...byBrand.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null;
}

/** Size of the largest group of dangerous verdicts naming the same impersonated brand; 0 when there is no campaign. */
export function campaignSize(outcomes: readonly Outcome[]): number {
  const byBrand = new Map<string, number>();
  for (const o of outcomes) {
    const v = o.verdict;
    if (v?.verdict !== "dangerous" || !v.impersonated_brand?.brand_id) continue;
    byBrand.set(v.impersonated_brand.brand_id, (byBrand.get(v.impersonated_brand.brand_id) ?? 0) + 1);
  }
  const max = Math.max(0, ...byBrand.values());
  return max >= 2 ? max : 0;
}

export const foundKeys = (total: number): string[] => foundClips(total);
export const speakFound = (lang: Lang, total: number): string => spoken(lang, foundKeys(total));

/** "The Investigator agent is checking the Nth message" (+ "of N" when there are several). */
export const checkingKeys = (i: number, total: number): string[] => [...investigatorStartClips(i), ...checkingClips(i, total).slice(1)];
export const speakChecking = (lang: Lang, i: number, total: number): string => spoken(lang, checkingKeys(i, total));

const STEP_TIER: Record<ProgressStep, "T0" | "T1" | "T2" | "T3"> = { lists: "T0", lookalike: "T1", wording: "T1", browser: "T2", ai: "T3" };

/** Investigator step clips that a progressive snapshot proves ran (the tier's intro line only). */
export function stepKeys(step: ProgressStep, v: Verdict): string[] {
  const map: Partial<Record<ProgressStep, InvestigatorStep | null>> = {
    lists: "lists",
    lookalike: "address",
    wording: "wording",
    browser: "page",
    ai: v.model_route === "cloud" ? "ai_second_look_cloud" : v.model_route === "local" ? "ai_second_look_local" : null,
  };
  const s = map[step];
  return s ? investigatorStepClips(s) : [];
}
/**
 * One tier, spoken: its intro, then up to two things THIS check found at that tier (from the real evidence of the
 * verdict stream). Each inner list is one spoken line; the screen shows exactly the same lines.
 */
export function stepGroups(step: ProgressStep, v: Verdict): string[][] {
  const intro = stepKeys(step, v);
  if (!intro.length) return [];
  return [intro, ...tierFindingGroups(v.evidence, STEP_TIER[step], v.impersonated_brand?.brand_id)];
}
/** The found-lines of one tier as text in the spoken language (what the progress panel shows under the tier). */
export const tierFoundText = (lang: Lang, step: ProgressStep, v: Verdict): string | undefined => {
  const groups = stepGroups(step, v).slice(1);
  return groups.length ? groups.map((g) => spoken(lang, g)).join(" ") : undefined;
};
export const speakStep = (lang: Lang, step: ProgressStep, v: Verdict): string => {
  const keys = stepKeys(step, v);
  return keys.length ? spoken(lang, keys) : "";
};

/** The arbiter's decision for a message, preceded by "the rules decided without AI" when no model was used. */
export function arbiterKeys(v: Verdict | null): string[] {
  const rules = v?.model_route === "none" ? ["investigator.rules_only"] : [];
  return [...rules, ...arbiterClips(v ? v.verdict : null, v?.risk_score ?? 0)];
}
export const speakArbiter = (lang: Lang, v: Verdict | null): string => spoken(lang, arbiterKeys(v));

/** The closing utterance: counts, what to do, and a wrap-up that names what the Sentinel actually did. */
export const finalKeys = (outcomes: readonly Outcome[], sentinel: "found" | "watching" | "unavailable" | "none"): string[] => finalClips(countOutcomes(outcomes), sentinel);
export const speakFinal = (lang: Lang, outcomes: readonly Outcome[], sentinel: "found" | "watching" | "unavailable" | "none"): string => spoken(lang, finalKeys(outcomes, sentinel));

/** The hand-over line, said when the results are handed to the Sentinel. */
export const speakHandover = (lang: Lang): string => spoken(lang, ["sentinel.handover"]);
/** Said only on timeout. */
export const speakUnavailable = (lang: Lang): string => spoken(lang, ["sentinel.unavailable"]);
/** Said when no check completed, instead of the hand-over. */
export const speakNothingChecked = (lang: Lang): string => spoken(lang, ["nothing_checked"]);
export const speakMicDenied = (lang: Lang): string => spoken(lang, ["mic.denied"]);
export const speakVoiceUnavailable = (lang: Lang): string => spoken(lang, ["voice.unavailable"]);
export const speakWatching = (lang: Lang): string => spoken(lang, ["sentinel.watching"]);
/** One spoken line per fact the incident shows (empty list when it shows nothing speakable). */
export const findingGroups = (f: SentinelFinding): string[][] => sentinelFindingGroups(f);
export const findingKeys = (f: SentinelFinding): string[] => findingGroups(f).flat();
export const speakFinding = (lang: Lang, f: SentinelFinding): string[] => findingGroups(f).map((g) => spoken(lang, g));
