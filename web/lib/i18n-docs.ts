/**
 * v2 strings owned by the check-result and Docs cards (web/design/v2/copy.json). Arabic is formal Modern
 * Standard Arabic. The word "safe" / «آمن» never appears (tests/unit/i18n-docs.test.ts). No digit-percent
 * literal: measured numbers come from the bundled artifact only.
 */
import type { Lang } from "./contracts";

const ar = {
  // Agent activity (check result)
  "act.title": "«بصير»، المحقّق، يفحص الرابط الآن…",
  "act.done": "أنهى «بصير» الفحص خلال {latency_s} ث",
  "act.done.nolat": "أنهى «بصير» الفحص",
  "act.step.known": "يقارنه ببلاغات الاحتيال المعروفة",
  "act.step.address": "يدقّق في العنوان",
  "act.step.visit": "يفتح الصفحة في بيئة معزولة بدلاً منك",
  "act.step.ai": "نظرة ثانية بالذكاء الاصطناعي (للحالات الغامضة فقط)",
  "act.st.done": "اكتملت",
  "act.st.running": "جارية…",
  "act.st.pending": "بالانتظار",
  "act.st.skipped": "لم تكن لازمة",
  "act.wait": "لا تضغط على الرابط إلى أن يكتمل الفحص.",
  "act.sentinel": "«درع» يقارن هذا الفحص بغيره لكشف الحملات مبكراً.",
  "act.label": "نشاط بصير، المحقّق",
  "act.steps": "خطوات الفحص",

  // Degraded because the page could not be opened
  "noopen.dns.title": "لا يوجد موقع يردّ على هذا العنوان — تعامل معه بحذر",
  "noopen.dns.body": "اسم هذا العنوان لا يقود إلى أي موقع حالياً، فلم نجد صفحة لنفتحها. قد يكون الرابط مكتوباً بشكل خاطئ أو أُغلق الموقع. لا تُدخل فيه أي بيانات، وافتح التطبيق أو الموقع الرسمي للجهة بنفسك.",
  "noopen.title": "تعذّر فتح الصفحة للتحقق — تعامل معها بحذر",
  "noopen.body": "لم نتمكن من فتح الصفحة نفسها، فلم نتحقق مما فيها. وهذا لا يعني أن الرابط موثوق؛ فلا تُدخل فيه أي بيانات، وافتح التطبيق أو الموقع الرسمي للجهة بنفسك.",

  // Technical details (check result)
  "tech.toggle": "تفاصيل تقنية",
  "tech.summary": "الأدلة والقواعد ودرجة الخطورة والتوقيتات، للمراجعين التقنيين.",
  "tech.docs": "كيف يصدر الحكم (التوثيق)",
  "tech.reasons": "الأدلة التي تسند كل سبب",
  "tech.reason": "السبب {n}",

  // Docs area
  "docs.eyebrow": "للمراجعين التقنيين",
  "docs.title": "التوثيق",
  "docs.lead": "التفاصيل التقنية وراء كل ما يذكره هذا الموقع: كيف بُني، وكيف يُؤمَّن، وكيف يُقاس.",
  "docs.architecture.title": "البنية",
  "docs.architecture.text": "الخدمات ومسار البيانات وعزل الشبكات.",
  "docs.agents.title": "أنماط الوكلاء",
  "docs.agents.text": "حلقة «بصير»، المحقّق، المحدودة، ومسار عمل «درع»، الحارس، والأدوات ونقاط الموافقة البشرية.",
  "docs.cascade.title": "طبقات الفحص T0–T3",
  "docs.cascade.text": "أربع طبقات تبدأ بالأسرع، ولا تتعمق إلا عند الحاجة.",
  "docs.arbiter.title": "المحكّم واحتساب الدرجة",
  "docs.arbiter.text": "السمات والأوزان والقواعد الحاسمة ونطاقات الحكم.",
  "docs.security.title": "الأمن",
  "docs.security.text": "نموذج التهديدات، والبيئة المعزولة، والتصدي لحقن التعليمات، وسياسة أمن المحتوى.",
  "docs.evals.title": "منهجية التقييم",
  "docs.evals.text": "مجموعات البيانات وتقسيمها، والمقاييس، وبوابات الدمج.",
  "docs.integration.title": "الربط: API و MCP و STIX",
  "docs.integration.text": "واجهة REST الإصدار 1، وخادم MCP، وتصدير STIX 2.1. جاهز للربط.",
  "docs.privacy.title": "هندسة الخصوصية",
  "docs.privacy.text": "تقليل البيانات، والحجب، والمسار السحابي والمسار السيادي.",
  "docs.read": "اقرأ",
  "docs.back": "لست متخصصاً؟ ابدأ من: كيف يحميك الوكيلان الذكيان.",
  "docs.nav": "صفحات التوثيق",
  "docs.crumb": "التوثيق",
  "docs.sources": "عرض المستند المصدري على GitHub",
  "docs.thr.title": "العتبات المضبوطة",
  "docs.thr.low": "العتبة الدنيا (τ low)",
  "docs.thr.high": "العتبة العليا (τ high)",
  "docs.thr.elow": "حدّ الخروج الأدنى (ε low)",
  "docs.thr.ehigh": "حدّ الخروج الأعلى (ε high)",
  "docs.thr.src": "مصدر الضبط",
  "docs.thr.from": "منقولة من ملف التقييم المنشور:",
  "docs.thr.none": "التقييم قيد الإنجاز. لا نعرض أي رقم قبل نشره.",
  "docs.prov.artifact": "ملف التقييم",
  "docs.prov.date": "تاريخ الإنشاء (UTC)",
  "docs.prov.dataset": "بصمة مجموعة البيانات",
  "docs.prov.sha": "نسخة الشيفرة",
  "docs.prov.scope": "النطاق المسجَّل",
  "docs.prov.results": "اعرض النتائج",
  "docs.agents.back": "كيف يحميك الوكيلان الذكيان",
  "docs.fig": "مخطط",

  // Authorities (trimmed)
  "ap.ifaces": "الواجهات الموثّقة",
  "ap.ifaces.more": "التفاصيل التقنية في التوثيق",
} as const;

export type DocKey = keyof typeof ar;

const en: Record<DocKey, string> = {
  "act.title": "The Investigator (Baseer | بصير) is checking your link…",
  "act.done": "The Investigator finished in {latency_s} s",
  "act.done.nolat": "The Investigator finished the check",
  "act.step.known": "Comparing with reported scams",
  "act.step.address": "Examining the address",
  "act.step.visit": "Opening the page in isolation, so you don't have to",
  "act.step.ai": "AI second look (unclear cases only)",
  "act.st.done": "Done",
  "act.st.running": "Working…",
  "act.st.pending": "Waiting",
  "act.st.skipped": "Not needed",
  "act.wait": "Don't tap the link until the check is complete.",
  "act.sentinel": "The Sentinel compares this check with others to spot campaigns early.",
  "act.label": "Investigator · بصير activity",
  "act.steps": "Check steps",

  "noopen.dns.title": "No website answers at this address — treat it with caution",
  "noopen.dns.body": "This address does not lead to any website right now, so there was no page to open. The link may be mistyped or the site may be gone. Do not enter any details there. Open the organisation's official app or website yourself instead.",
  "noopen.title": "We couldn't open this page to check it — treat it with caution",
  "noopen.body": "We could not open the page itself, so we could not check what is on it. That is not a sign the link is fine: do not enter any details there. Open the organisation's official app or website yourself instead.",

  "tech.toggle": "Technical details",
  "tech.summary": "Evidence, rules, risk score and timings, for technical reviewers.",
  "tech.docs": "How a verdict is reached (Docs)",
  "tech.reasons": "Evidence behind each reason",
  "tech.reason": "Reason {n}",

  "docs.eyebrow": "For technical reviewers",
  "docs.title": "Docs",
  "docs.lead": "The technical detail behind every statement on this site: how it is built, how it is secured and how it is measured.",
  "docs.architecture.title": "Architecture",
  "docs.architecture.text": "Services, data flow and network isolation.",
  "docs.agents.title": "Agent patterns",
  "docs.agents.text": "The bounded loop of the Investigator (Baseer | بصير), the workflow of the Sentinel (Dir' | درع), tools and human gates.",
  "docs.cascade.title": "Cascade T0–T3",
  "docs.cascade.text": "Four tiers, fastest first; deeper only when needed.",
  "docs.arbiter.title": "Arbiter and scoring",
  "docs.arbiter.text": "Features, weights, hard rules and verdict bands.",
  "docs.security.title": "Security",
  "docs.security.text": "Threat model, sandbox, prompt-injection defence and CSP.",
  "docs.evals.title": "Evaluation methodology",
  "docs.evals.text": "Datasets, splits, metrics and merge gates.",
  "docs.integration.title": "Integration: API, MCP, STIX",
  "docs.integration.text": "REST v1, an MCP server and STIX 2.1 export. Ready to connect.",
  "docs.privacy.title": "Privacy engineering",
  "docs.privacy.text": "Data minimisation, redaction, cloud and sovereign routes.",
  "docs.read": "Read",
  "docs.back": "Not technical? Start with how the AI agents protect you.",
  "docs.nav": "Documentation pages",
  "docs.crumb": "Docs",
  "docs.sources": "View the source document on GitHub",
  "docs.thr.title": "Fitted thresholds",
  "docs.thr.low": "Low threshold (τ low)",
  "docs.thr.high": "High threshold (τ high)",
  "docs.thr.elow": "Early-exit low bound (ε low)",
  "docs.thr.ehigh": "Early-exit high bound (ε high)",
  "docs.thr.src": "Fitted on",
  "docs.thr.from": "Read from the published evaluation file:",
  "docs.thr.none": "Evaluation in progress. No number is shown before it is published.",
  "docs.prov.artifact": "Evaluation file",
  "docs.prov.date": "Created (UTC)",
  "docs.prov.dataset": "Dataset fingerprint",
  "docs.prov.sha": "Code revision",
  "docs.prov.scope": "Scope as recorded",
  "docs.prov.results": "See the results",
  "docs.agents.back": "How the AI agents protect you",
  "docs.fig": "Diagram",

  "ap.ifaces": "Documented interfaces",
  "ap.ifaces.more": "Technical detail in Docs",
};

export const DOC_MESSAGES: Record<Lang, Record<DocKey, string>> = { ar, en };

export function dt(lang: Lang, key: DocKey, vars?: Record<string, string | number>): string {
  let text: string = DOC_MESSAGES[lang][key];
  if (vars) for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v));
  return text;
}
