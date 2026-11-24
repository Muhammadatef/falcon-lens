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

export const speakFound = (lang: Lang, total: number): string => spoken(lang, foundClips(total));

/** "The Investigator agent is checking the Nth message" (+ "of N" when there are several). */
export const speakChecking = (lang: Lang, i: number, total: number): string => spoken(lang, [...investigatorStartClips(i), ...checkingClips(i, total).slice(1)]);

/** Investigator step lines that a progressive snapshot proves ran. "wording" has no spoken line (screen only). */
export function speakStep(lang: Lang, step: ProgressStep, v: Verdict): string {
  const map: Partial<Record<ProgressStep, InvestigatorStep | null>> = {
    lists: "lists",
    lookalike: "address",
    browser: "page",
    ai: v.model_route === "cloud" ? "ai_second_look_cloud" : v.model_route === "local" ? "ai_second_look_local" : null,
  };
  const s = map[step];
  return s ? spoken(lang, investigatorStepClips(s)) : "";
}

/** The arbiter's decision for a message, preceded by "the rules decided without AI" when no model was used. */
export function speakArbiter(lang: Lang, v: Verdict | null): string {
  const rules = v?.model_route === "none" ? ["investigator.rules_only"] : [];
  return spoken(lang, [...rules, ...arbiterClips(v ? v.verdict : null, v?.risk_score ?? 0)]);
}

/** The closing utterance: counts, what to do, the Sentinel hand-over, and the wrap-up naming both agents. */
export const speakFinal = (lang: Lang, outcomes: readonly Outcome[]): string => spoken(lang, finalClips(countOutcomes(outcomes), campaignSize(outcomes)));
