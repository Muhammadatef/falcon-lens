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
  sentinelFindingClips,
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

/** Investigator step clips that a progressive snapshot proves ran. "wording" has no spoken line (screen only). */
export function stepKeys(step: ProgressStep, v: Verdict): string[] {
  const map: Partial<Record<ProgressStep, InvestigatorStep | null>> = {
    lists: "lists",
    lookalike: "address",
    browser: "page",
    ai: v.model_route === "cloud" ? "ai_second_look_cloud" : v.model_route === "local" ? "ai_second_look_local" : null,
  };
  const s = map[step];
  return s ? investigatorStepClips(s) : [];
}
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
export const findingKeys = (f: SentinelFinding): string[] => sentinelFindingClips(f);
export const speakFinding = (lang: Lang, f: SentinelFinding): string[] => findingKeys(f).map((k) => spoken(lang, [k]));
