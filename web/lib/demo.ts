/**
 * DEMO DATA. Loaded only when a page is opened with `?demo=1` (dynamic import) and by
 * tests. Every object carries `source: "fixture"` or `"synthetic"`, so the UI shows the
 * DEMO DATA badge on it. Nothing in here is ever shown for a real check.
 *
 * The brand is the invented "Falcon Demo Bank" (data/brands.yaml); URLs are defanged and
 * use reserved TLDs (.test / .invalid). Channels mirror config/reporting_channels.yaml.
 */
import type { AgentTrace, TraceStep } from "./agent-trace";
import { TIERS, type Evidence, type Incident, type ReportChannel, type Tier, type Verdict, type VerdictLabel } from "./contracts";

export const DEMO_BRAND = { brand_id: "falcon_demo_bank", name_ar: "بنك الصقر التجريبي", name_en: "Falcon Demo Bank" } as const;

const CHANNELS: ReportChannel[] = [
  { label_ar: "الطوارئ", label_en: "Emergency", value: "999", source_url: "https://www.adpolice.gov.ae/en/", retrieved_at: "2026-11-22" },
  { label_ar: "خدمة أمان (شرطة أبوظبي)", label_en: "Aman service (Abu Dhabi Police)", value: "8002626 · aman.adpolice.gov.ae", source_url: "https://www.adpolice.gov.ae/en/", retrieved_at: "2026-11-22" },
  { label_ar: "بوابة البلاغات لشرطة أبوظبي", label_en: "Abu Dhabi Police complaints portal", value: "cas.adpolice.gov.ae", source_url: "https://www.adpolice.gov.ae/en/", retrieved_at: "2026-11-22" },
];

const REPORT = { ar: "أبلغ عبر القنوات الرسمية لشرطة أبوظبي.", en: "Report it through Abu Dhabi Police official channels.", channels: CHANNELS };

const CAUTION = {
  ar: ["عدم وجود علامات تحذير ليس ضماناً.", "لا تشارك رمز التحقق (OTP) مع أي شخص، مهما كان السبب.", "إذا استعجلك أحد أو طلب تحويل مال، توقّف وتحقق."],
  en: ["Finding no warning signs is not a guarantee.", "Never share a one-time code (OTP) with anyone, for any reason.", "If someone rushes you or asks for a money transfer, stop and verify."],
};

const ev = (e: Omit<Evidence, "hard_rule"> & { hard_rule?: string | null }): Evidence => ({ hard_rule: null, ...e });

export const DEMO_DANGEROUS: Verdict = {
  schema_version: "1.0",
  verdict_id: "vd_01KB0DEM0DATA0000000000001",
  input_type: "url",
  canonical_url: "hxxps://falcon-demo-bank-secure[.]test/login",
  verdict: "dangerous",
  risk_score: 97,
  calibrated_probability: 0.97,
  impersonated_brand: { ...DEMO_BRAND, official_domains: ["falcon-demo-bank[.]test"] },
  evidence: [
    ev({ id: "ev_rep0feed01", signal: "rep.openphish", family: "reputation", observed: false, display: { ar: "غير مدرج في قوائم الحظر المعروفة حتى الآن", en: "Not on known blocklists yet" }, weight: 0, polarity: "neutral", source: "openphish", tier: "T0" }),
    ev({ id: "ev_url0combo1", signal: "url.combosquat", family: "url", observed: { brand_id: "falcon_demo_bank", token: "secure" }, display: { ar: "العنوان يضيف كلمة «secure» إلى اسم البنك", en: "The address adds the word “secure” to the bank's name" }, weight: 2.0, polarity: "risk", source: "computed", tier: "T1" }),
    ev({ id: "ev_dom0age001", signal: "domain.age_days", family: "domain", observed: 2, display: { ar: "النطاق مسجّل قبل يومين فقط", en: "The domain was registered only 2 days ago" }, weight: 2.5, polarity: "risk", source: "rdap", tier: "T1" }),
    ev({ id: "ev_dom0cert01", signal: "domain.cert_age_days", family: "domain", observed: 1, display: { ar: "شهادة الموقع صدرت أمس", en: "The site certificate was issued yesterday" }, weight: 0.8, polarity: "risk", source: "crt", tier: "T1" }),
    ev({ id: "ev_page0form1", signal: "page.cred_form", family: "page", observed: { fields: ["password", "otp"] }, display: { ar: "الصفحة تطلب كلمة المرور ورمز التحقق (OTP)", en: "The page asks for a password and a one-time code (OTP)" }, weight: 1.5, polarity: "risk", source: "sandbox", tier: "T2" }),
    ev({ id: "ev_page0post1", signal: "page.cross_origin_post", family: "page", observed: "hxxps://collector[.]invalid/hook", display: { ar: "ما تكتبه يُرسل إلى خادم لا علاقة له بالبنك", en: "What you type is sent to a server unrelated to the bank" }, weight: 3.0, polarity: "risk", source: "sandbox", tier: "T2" }),
    ev({ id: "ev_brand0own1", signal: "brand.claimed_not_owned", family: "brand", observed: { brand_id: "falcon_demo_bank", registrable_domain: "falcon-demo-bank-secure[.]test" }, display: { ar: "تدّعي أنها «بنك الصقر التجريبي» لكن النطاق ليس من نطاقات البنك الرسمية", en: "It claims to be Falcon Demo Bank, but the domain is not one of the bank's official domains" }, weight: 3.0, polarity: "risk", hard_rule: "H1", source: "registry", tier: "T2" }),
  ],
  reasons: [
    { ar: "الصفحة تنتحل اسم «بنك الصقر التجريبي» وعنوانها ليس من عناوين البنك الرسمية.", en: "The page poses as Falcon Demo Bank, but its address is not one of the bank's official addresses.", evidence_ids: ["ev_brand0own1"], generated_by: "template" },
    { ar: "تطلب كلمة المرور ورمز التحقق وترسلهما إلى خادم آخر.", en: "It asks for your password and one-time code and sends them to another server.", evidence_ids: ["ev_page0form1", "ev_page0post1"], generated_by: "template" },
    { ar: "العنوان جديد جداً: سُجّل قبل يومين.", en: "The address is brand new: registered 2 days ago.", evidence_ids: ["ev_dom0age001"], generated_by: "template" },
  ],
  actions: {
    now: {
      ar: ["لا تفتح الرابط ولا تُدخل أي بيانات.", "احذف الرسالة واحظر المرسل.", "ادخل إلى حسابك من تطبيق البنك الرسمي فقط."],
      en: ["Don't open the link or enter any details.", "Delete the message and block the sender.", "Reach your account only through the bank's official app."],
    },
    if_already_acted: {
      ar: ["اتصل ببنكك فوراً على الرقم المطبوع على بطاقتك واطلب إيقافها.", "غيّر كلمة المرور من التطبيق الرسمي.", "راقب حسابك وبلّغ البنك عن أي عملية لا تعرفها."],
      en: ["Call your bank now on the number printed on your card and ask to block it.", "Change your password from the official app.", "Watch your account and tell the bank about any transaction you don't recognise."],
    },
    report: REPORT,
  },
  tier_reached: "T2",
  model_route: "none",
  degraded: false,
  final: true,
  trace: [
    { step: 1, kind: "tier", name: "T0", summary: "Blocklists and cache checked: no match.", evidence_added: ["ev_rep0feed01"], ms: 40 },
    { step: 2, kind: "tool", name: "rdap_lookup", summary: "Domain registration and certificate age read.", evidence_added: ["ev_url0combo1", "ev_dom0age001", "ev_dom0cert01"], ms: 570 },
    { step: 3, kind: "tool", name: "sandbox_visit", summary: "Page opened once in the isolated browser; nothing was typed.", evidence_added: ["ev_page0form1", "ev_page0post1"], ms: 2100 },
    { step: 4, kind: "rule", name: "H1", summary: "Hard rule H1: page claims a brand whose official domains do not include this one.", evidence_added: ["ev_brand0own1"], ms: 3 },
  ],
  source: "fixture",
  latency_ms: 2840,
  created_at: "2026-11-22T10:02:00Z",
};

export const DEMO_NWS: Verdict = {
  schema_version: "1.0",
  verdict_id: "vd_01KB0DEM0DATA0000000000003",
  input_type: "url",
  canonical_url: "hxxps://falcon-demo-bank[.]test/",
  verdict: "no_warning_signs",
  risk_score: 3,
  calibrated_probability: 0.03,
  impersonated_brand: null,
  evidence: [
    ev({ id: "ev_rep0feed02", signal: "rep.openphish", family: "reputation", observed: false, display: { ar: "غير مدرج في قوائم الحظر المعروفة", en: "Not on known blocklists" }, weight: 0, polarity: "neutral", source: "openphish", tier: "T0" }),
    ev({ id: "ev_reg0off001", signal: "registry.verified_official", family: "brand", observed: { brand_id: "falcon_demo_bank" }, display: { ar: "النطاق ضمن النطاقات الرسمية الموثّقة لبنك الصقر التجريبي", en: "The domain is on Falcon Demo Bank's verified official list" }, weight: -4.0, polarity: "trust", hard_rule: "H3", source: "registry", tier: "T1" }),
    ev({ id: "ev_dom0age002", signal: "domain.age_days", family: "domain", observed: 4100, display: { ar: "النطاق مسجّل منذ أكثر من عشر سنوات", en: "The domain was registered more than ten years ago" }, weight: -1.0, polarity: "trust", source: "rdap", tier: "T1" }),
  ],
  reasons: [
    { ar: "العنوان ضمن النطاقات الرسمية الموثّقة لبنك الصقر التجريبي.", en: "The address is on Falcon Demo Bank's verified official domain list.", evidence_ids: ["ev_reg0off001"], generated_by: "template" },
    { ar: "النطاق قديم وليس في قوائم الحظر المعروفة.", en: "The domain is old and is not on known blocklists.", evidence_ids: ["ev_dom0age002", "ev_rep0feed02"], generated_by: "template" },
  ],
  actions: {
    now: { ar: ["تأكد أن العنوان في متصفحك يطابق هذا العنوان حرفاً بحرف."], en: ["Make sure the address in your browser matches this one, character for character."] },
    if_already_acted: { ar: ["إذا طُلب منك شيء غير معتاد بعد الدخول، توقّف واتصل بالبنك."], en: ["If you were asked for anything unusual after signing in, stop and call the bank."] },
    report: REPORT,
    caution: CAUTION,
  },
  tier_reached: "T1",
  model_route: "none",
  degraded: false,
  final: true,
  trace: [
    { step: 1, kind: "tier", name: "T0", summary: "Blocklists and cache checked: no match.", evidence_added: ["ev_rep0feed02"], ms: 38 },
    { step: 2, kind: "rule", name: "H3", summary: "Hard rule H3: domain is on the brand's verified official list.", evidence_added: ["ev_reg0off001", "ev_dom0age002"], ms: 500 },
  ],
  source: "fixture",
  latency_ms: 540,
  created_at: "2026-11-22T10:20:00Z",
};

export interface StreamStep {
  delayMs: number;
  verdict: Verdict;
}

interface PartialSpec {
  tier: Tier;
  delayMs: number;
  verdict: VerdictLabel;
  risk: number;
  ms: number;
}

/** Builds the progressive events the API emits: one whole Verdict per completed tier. */
export function buildStream(final: Verdict, specs: PartialSpec[]): StreamStep[] {
  return specs.map((s, k) => {
    const last = k === specs.length - 1;
    if (last) return { delayMs: s.delayMs, verdict: final };
    const upto = TIERS.indexOf(s.tier);
    const evidence = final.evidence.filter((e) => TIERS.indexOf(e.tier) <= upto);
    const ids = new Set(evidence.map((e) => e.id));
    const partial: Verdict = {
      ...final,
      verdict: s.verdict,
      risk_score: s.risk,
      calibrated_probability: s.risk / 100,
      tier_reached: s.tier,
      latency_ms: s.ms,
      evidence,
      reasons: [],
      impersonated_brand: null,
      actions: { ...final.actions, caution: s.verdict === "no_warning_signs" ? CAUTION : final.actions.caution },
      trace: final.trace?.filter((t) => (t.evidence_added ?? []).every((id) => ids.has(id))),
      final: false,
    };
    return { delayMs: s.delayMs, verdict: partial };
  });
}

export const DEMO_STREAMS: Record<"danger" | "nws", StreamStep[]> = {
  danger: buildStream(DEMO_DANGEROUS, [
    { tier: "T0", delayMs: 700, verdict: "no_warning_signs", risk: 22, ms: 40 },
    { tier: "T1", delayMs: 1300, verdict: "suspicious", risk: 68, ms: 610 },
    { tier: "T2", delayMs: 2100, verdict: "dangerous", risk: 97, ms: 2840 },
  ]),
  nws: buildStream(DEMO_NWS, [
    { tier: "T0", delayMs: 700, verdict: "no_warning_signs", risk: 20, ms: 38 },
    { tier: "T1", delayMs: 1500, verdict: "no_warning_signs", risk: 3, ms: 540 },
  ]),
};

export const DEMO_CAMPAIGNS = [
  {
    campaign_id: "inc_01KB0DEM0DATA0000000000002", severity: "high", count: 3, last_seen: "2026-11-22T10:12:00Z", source: "synthetic",
    series: [0, 0, 0, 0, 0, 0, 0, 0, 20, 45, 70, 100],
    title: { ar: "صفحات دخول مزيّفة باسم «بنك الصقر التجريبي»", en: "Fake sign-in pages using the Falcon Demo Bank name" },
    advice: { ar: "لا تدخل إلى حسابك من رابط وصلك في رسالة.", en: "Never sign in from a link that arrived in a message." },
  },
  {
    campaign_id: "inc_01KB0DEM0DATA0000000000006", severity: "medium", count: 7, last_seen: "2026-11-22T09:40:00Z", source: "synthetic",
    series: [10, 25, 20, 40, 35, 55, 30, 45, 60, 40, 50, 35],
    title: { ar: "رسائل «رسوم توصيل» بروابط مختصرة", en: "“Delivery fee” messages with shortened links" },
    advice: { ar: "تتبّع شحنتك من تطبيق شركة التوصيل نفسه.", en: "Track your parcel in the courier's own app." },
  },
  {
    campaign_id: "inc_01KB0DEM0DATA0000000000007", severity: "low", count: 4, last_seen: "2026-11-22T08:05:00Z", source: "synthetic",
    series: [30, 20, 35, 15, 25, 10, 20, 15, 10, 20, 10, 15],
    title: { ar: "رسائل «حدّث بياناتك» تطلب رمز التحقق", en: "“Update your details” messages asking for a one-time code" },
    advice: { ar: "رمز التحقق لك وحدك. لا تعطه لأحد.", en: "A one-time code is yours alone. Give it to no one." },
  },
];

export const DEMO_INCIDENT: Incident = {
  incident_id: "inc_01KB0DEM0DATA0000000000002",
  type: "campaign",
  severity: "high",
  severity_reason: { ar: "ثلاثة نطاقات بالبصمة نفسها خلال ربع ساعة، وكلها تطلب بيانات الدخول.", en: "Three domains with the same page fingerprint within 15 minutes, all asking for sign-in details.", evidence_ids: ["ev_brand0own1", "ev_page0form1"] },
  status: "awaiting_approval",
  brand_id: "falcon_demo_bank",
  rule_ids: ["R1"],
  correlation_keys: { brand: "falcon_demo_bank", dom_simhash_bucket: "9f3a", window: "15m", registrar: "demo-registrar" },
  indicators: [
    { kind: "domain", value_defanged: "falcon-demo-bank-secure[.]test", first_seen: "2026-11-22T10:02:00Z", blocked_until: "2026-11-23T10:11:00Z" },
    { kind: "domain", value_defanged: "falcon-demo-bank-login[.]test", first_seen: "2026-11-22T10:09:00Z", blocked_until: "2026-11-23T10:11:00Z" },
    { kind: "domain", value_defanged: "falcondemobank-verify[.]test", first_seen: "2026-11-22T10:11:00Z", blocked_until: "2026-11-23T10:11:00Z" },
    { kind: "dom_hash", value_defanged: "simhash:9f3a…c21e", first_seen: "2026-11-22T10:02:00Z", blocked_until: null },
  ],
  linked_verdicts: ["vd_01KB0DEM0DATA0000000000001", "vd_01KB0DEM0DATA0000000000004", "vd_01KB0DEM0DATA0000000000005"],
  timeline: [
    { at: "2026-11-22T10:02:00Z", what: "First dangerous verdict (hard rule H1: brand mismatch)" },
    { at: "2026-11-22T10:09:00Z", what: "Second domain with the same page fingerprint" },
    { at: "2026-11-22T10:11:00Z", what: "Rule R1 fired: 3 linked checks in 15 minutes" },
    { at: "2026-11-22T10:11:20Z", what: "Indicators blocked internally (automatic, reversible)" },
    { at: "2026-11-22T10:12:00Z", what: "Takedown draft ready, waiting for human approval" },
  ],
  summary: { ar: "حملة تنتحل اسم «بنك الصقر التجريبي» عبر ثلاثة نطاقات متشابهة تستضيف الصفحة نفسها.", en: "A campaign posing as Falcon Demo Bank across three lookalike domains hosting the same page.", generated_by: "template", model_route: "none" },
  actions: [
    { action_id: "act_block_001", tool: "block_indicator", mode: "internal_auto", status: "executed", evidence_ids: ["ev_brand0own1"], approved_by: null, at: "2026-11-22T10:11:20Z" },
    { action_id: "act_board_001", tool: "update_campaign_board", mode: "internal_auto", status: "executed", evidence_ids: ["ev_brand0own1"], approved_by: null, at: "2026-11-22T10:11:25Z" },
    {
      action_id: "act_takedown_001", tool: "draft_takedown", mode: "external_draft", status: "awaiting_approval",
      draft: { recipient_kind: "registrar", subject: "Takedown request: 3 lookalike domains (DEMO)", body_ar: "مسودة تجريبية: طلب إيقاف ثلاثة نطاقات تنتحل اسم بنك الصقر التجريبي، مع الأدلة المرفقة.", body_en: "Demo draft: request to suspend three domains posing as Falcon Demo Bank, with the attached evidence." },
      evidence_ids: ["ev_brand0own1", "ev_page0post1"], approved_by: null, at: "2026-11-22T10:12:00Z",
    },
  ],
  source: "synthetic",
  created_at: "2026-11-22T10:11:00Z",
  updated_at: "2026-11-22T10:12:00Z",
};

/* Synthetic Sentinel agent trace for DEMO_INCIDENT (?demo=1). Shape: contracts/agent_trace.schema.json. */
const demoStep = (seq: number, node: TraceStep["node"], patch: Partial<TraceStep>): TraceStep => ({
  seq, node, started_at: `2026-11-22T10:11:${String(seq * 3).padStart(2, "0")}Z`, duration_ms: 40, status: "completed",
  summary_en: "", summary_ar: "", tools: [], llm: null, budget: { steps_used: seq, tokens_used: 0, elapsed_ms: seq * 300 }, error_code: null, ...patch,
});
const demoLlm = (tokens_in: number, tokens_out: number) => ({ route: "local" as const, model: "demo-model", tokens_in, tokens_out, cost_usd: 0, repaired: false, fallback_template: false });
export const DEMO_TRACE: AgentTrace = {
  incident_id: DEMO_INCIDENT.incident_id,
  thread_id: DEMO_INCIDENT.incident_id,
  runs: [{
    run_id: "run_demo0000000000a1", started_at: "2026-11-22T10:11:03Z", finished_at: "2026-11-22T10:12:00Z", status: "interrupted",
    interrupt: { action_id: "act_takedown_001", tool: "draft_takedown", waiting_since: "2026-11-22T10:12:00Z", pending_count: 1 },
    steps: [
      demoStep(1, "enrich", { duration_ms: 212, summary_en: "Gathered context with 4 read tools: 4 indicators, 9 evidence ids.", summary_ar: "جُمع السياق بـ 4 أدوات قراءة: 4 مؤشرات و9 معرّف دليل.", tools: ["search_verdicts", "find_related_domains", "get_past_incidents", "feed_status"].map((name) => ({ name, mode: "read" as const, status: "ok" as const, evidence_ids: [], duration_ms: 40 })) }),
      demoStep(2, "compare", { summary_en: "Compared indicators: 2 related domains, 0 past incidents. Deterministic, no model.", summary_ar: "قورنت المؤشرات: 2 نطاقات مرتبطة و0 حوادث سابقة. بلا نموذج." }),
      demoStep(3, "assess", { duration_ms: 1450, summary_en: "The severity reason was written by the model and checked against the evidence.", summary_ar: "كتب النموذج سبب الخطورة وجرى التحقق منه مقابل الأدلة.", llm: demoLlm(820, 140), tools: [{ name: "upsert_incident", mode: "internal_auto", status: "ok", evidence_ids: ["rule:R1"], duration_ms: 12 }] }),
      demoStep(4, "summarise", { duration_ms: 1810, summary_en: "The summary was written from a template (model output not accepted).", summary_ar: "كُتب الملخص من قالب (لم يُقبل مخرج النموذج).", llm: { ...demoLlm(0, 0), route: "none", fallback_template: true }, tools: [{ name: "upsert_incident", mode: "internal_auto", status: "ok", evidence_ids: ["rule:R1"], duration_ms: 11 }] }),
      demoStep(5, "propose", { duration_ms: 1320, summary_en: "Proposed 5 actions; 0 model proposals were rejected by the validator.", summary_ar: "اقتُرحت 5 إجراءات، ورفض المدقق 0 من مقترحات النموذج.", llm: demoLlm(910, 220) }),
      demoStep(6, "act", { duration_ms: 305, status: "interrupted", summary_en: "Waiting for a human to decide on 1 external draft(s). Nothing is sent before approval.", summary_ar: "بانتظار قرار بشري على 1 مسودة خارجية. لا يُرسل شيء قبل الموافقة.", tools: [
        { name: "block_indicator", mode: "internal_auto", status: "ok", evidence_ids: ["ev_brand0own1"], duration_ms: 18 },
        { name: "update_campaign_board", mode: "internal_auto", status: "ok", evidence_ids: [], duration_ms: 9 },
        { name: "draft_takedown", mode: "external_draft", status: "ok", evidence_ids: ["ev_brand0own1"], duration_ms: 6 },
      ] }),
    ],
  }],
};
