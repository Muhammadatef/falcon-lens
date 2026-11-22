/**
 * TEST FIXTURES (not real sites, not real data). Built on the demo verdicts for the
 * invented "Falcon Demo Bank". Shared by unit tests (schema validation) and e2e tests.
 */
import type { Verdict } from "../lib/contracts";
import { DEMO_DANGEROUS, DEMO_NWS, buildStream, type StreamStep } from "../lib/demo";

/** Every string an attacker controls in a verdict, loaded with markup and script payloads. */
export const XSS = {
  img: `<img src=x onerror="window.__xss=(window.__xss||0)+1">`,
  script: `<script>window.__xss=(window.__xss||0)+1</script>`,
  svg: `"><svg/onload=window.__xss=1>`,
  jsUrl: "javascript:window.__xss=1//",
  attr: `' autofocus onfocus='window.__xss=1`,
  bidi: "‮gnp.exe‬",
} as const;

export const withId = (v: Verdict, id: string, patch: Partial<Verdict> = {}): Verdict => ({ ...v, verdict_id: id, source: "live", ...patch });

export function dangerousStream(id: string): StreamStep[] {
  return buildStream(withId(DEMO_DANGEROUS, id), [
    { tier: "T0", delayMs: 250, verdict: "no_warning_signs", risk: 22, ms: 40 },
    { tier: "T1", delayMs: 450, verdict: "suspicious", risk: 68, ms: 610 },
    { tier: "T2", delayMs: 900, verdict: "dangerous", risk: 97, ms: 2840 },
  ]);
}

export function nwsStream(id: string): StreamStep[] {
  return buildStream(withId(DEMO_NWS, id), [
    { tier: "T0", delayMs: 250, verdict: "no_warning_signs", risk: 20, ms: 38 },
    { tier: "T1", delayMs: 500, verdict: "no_warning_signs", risk: 3, ms: 540 },
  ]);
}

/** Degraded: a source timed out, so the verdict is suspicious (never no_warning_signs). */
export function degradedVerdict(id: string): Verdict {
  return withId(DEMO_DANGEROUS, id, {
    verdict: "suspicious",
    risk_score: 58,
    calibrated_probability: 0.58,
    impersonated_brand: null,
    degraded: true,
    degraded_reasons: ["sandbox_timeout", "rdap_unavailable"],
    tier_reached: "T2",
    evidence: [
      ...DEMO_DANGEROUS.evidence.slice(0, 2),
      { id: "ev_sandbox0err", signal: "page.visit", family: "page", observed: null, display: { ar: "لم نتمكن من فتح الصفحة في المتصفح المعزول", en: "We could not open the page in the isolated browser" }, weight: 0, polarity: "neutral", hard_rule: null, source: "sandbox", tier: "T2", error: "timeout" },
    ],
    reasons: [{ ar: "العنوان يضيف كلمة إلى اسم بنك معروف.", en: "The address adds a word to a known bank's name.", evidence_ids: ["ev_url0combo1"], generated_by: "template" }],
    trace: [{ step: 1, kind: "tool", name: "sandbox_visit", summary: "Sandbox visit timed out after 6 s.", evidence_added: ["ev_sandbox0err"], ms: 6000 }],
  });
}

/** A hostile verdict: payloads in every attacker-influenced string the UI renders. */
export function xssVerdict(id: string): Verdict {
  return withId(DEMO_DANGEROUS, id, {
    canonical_url: `hxxps://evil[.]test/${XSS.img}?next=${XSS.jsUrl}`,
    impersonated_brand: { brand_id: "falcon_demo_bank", name_ar: `بنك ${XSS.script}`, name_en: `Bank ${XSS.script}`, official_domains: [] },
    evidence: DEMO_DANGEROUS.evidence.map((e, i) =>
      i === 4 ? { ...e, display: { ar: `نموذج ${XSS.img}`, en: `Form ${XSS.img}` }, source: XSS.svg, hard_rule: XSS.attr } : i === 5 ? { ...e, observed: XSS.jsUrl, display: { ar: XSS.bidi, en: XSS.bidi } } : e,
    ),
    reasons: [
      { ar: `سبب ${XSS.script}`, en: `Reason ${XSS.script}`, evidence_ids: ["ev_page0form1"], generated_by: "llm" },
      { ar: `سبب ${XSS.svg}`, en: `Reason ${XSS.svg}`, evidence_ids: ["ev_page0post1"], generated_by: "llm" },
    ],
    actions: {
      now: { ar: [`افعل ${XSS.img}`], en: [`Do ${XSS.img}`] },
      if_already_acted: { ar: [XSS.attr], en: [XSS.attr] },
      report: { ar: XSS.script, en: XSS.script, channels: [{ label_ar: XSS.img, label_en: XSS.img, value: XSS.jsUrl, source_url: XSS.jsUrl, retrieved_at: "2026-11-22" }] },
    },
    trace: [{ step: 1, kind: "llm", name: XSS.svg, summary: `Model said ${XSS.script} ${XSS.img}`, evidence_added: ["ev_page0form1"], ms: 12 }],
  });
}
