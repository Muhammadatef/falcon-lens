/**
 * Strings for the explainer on /campaigns. Arabic is formal Modern Standard Arabic. Never the words
 * "safe" / «آمن». No numbers: only what the Sentinel code does is described (services/sentinel/rules.yaml).
 */
import type { Lang } from "./contracts";

const ar = {
  "cx.intro": "الحملة هي عدة بلاغات وفحوص منفصلة تبيّن أنها الاحتيال نفسه: العلامة المنتحَلة نفسها، وقالب الصفحة نفسه، والبنية التقنية نفسها. يربطها «درع»، الحارس، وهو وكيل ذكاء اصطناعي، تلقائياً.",
  "cx.toggle": "كيف يعمل هذا؟",
  "cx.toggle.hint": "لماذا تهمّ الحملات، وكيف تُبنى، وكيف تقرأ البطاقة",
  "cx.region": "شرح لوحة الحملات",
  "cx.why.h": "لماذا يهمّ هذا؟",
  "cx.why.res.h": "للمقيمين",
  "cx.why.res": "تنبيه إلى عمليات احتيال نشطة الآن، قبل أن تضغط على أي رابط.",
  "cx.why.auth.h": "للجهات المختصة",
  "cx.why.auth": "جاهز للربط وغير مرتبط حالياً. عرض واحد للحملة بدلاً من مئات البلاغات المفردة، وطلبات إزالة أبكر، وإمكانية مشاركتها بصيغة STIX للاستخبارات.",
  "cx.why.safe.h": "سرعة بلا مخاطرة",
  "cx.why.safe": "يجهّز «درع» مسوّدات طلبات الإزالة والبلاغ للشرطة، ولا يغادر شيء النظام قبل أن يوافق ضابط.",
  "cx.how.h": "كيف تُبنى الحملة؟",
  "cx.how.1": "تصل الفحوص والبلاغات.",
  "cx.how.2": "يربطها «درع» ببصمات مشتركة: العلامة، وقالب الصفحة، ونمط النطاق، والتوقيت.",
  "cx.how.3": "قواعد ثابتة، لا الذكاء الاصطناعي، هي التي تقرّر أنها حملة.",
  "cx.how.4": "يكتب الذكاء الاصطناعي ملخصاً بلغتين، وتنتظر المسوّدات موافقة بشرية.",
  "cx.read.h": "كيف تقرأ البطاقة؟",
  "cx.read.title": "العنوان: اسم الحملة والعلامة التي تنتحلها.",
  "cx.read.count": "فحوص مرتبطة: عدد الفحوص التي ضمّها «درع» إلى هذه الحملة.",
  "cx.read.seen": "آخر ظهور: وقت آخر فحص ارتبط بها.",
  "cx.read.sev": "الشدة: حرجة أو عالية أو متوسطة أو منخفضة. الشكل يرافق الكلمة، فلا يعتمد المعنى على اللون.",
  "cx.read.bars": "الأعمدة الصغيرة: نشاط الحملة عبر الفترات الأخيرة، والعمود الأخير هو الأحدث.",
  "cx.read.source": "وسم «بيانات اصطناعية» أو «إعادة تشغيل»: يعني أن البطاقة ليست بلاغاً حياً.",
  "cx.read.advice": "السطر الأخير: ما ننصح به الآن.",
  "cx.note": "تُعرض النطاقات بصيغة معطّلة مثل example[.]com حتى لا يمكن الضغط عليها بالخطأ. البيانات في هذا العرض التجريبي معاد تشغيلها أو اصطناعية حيثما وُسمت بذلك.",
  "cx.more": "التفاصيل التقنية في صفحة الوكلاء",
} as const;

const en: Record<keyof typeof ar, string> = {
  "cx.intro": "A campaign is many separate reports and checks that turn out to be the same scam: the same fake brand, the same page kit, the same infrastructure. The Sentinel (Dir' | درع), an AI agent, links them automatically.",
  "cx.toggle": "How this works",
  "cx.toggle.hint": "Why campaigns matter, how they are built, how to read a card",
  "cx.region": "About the campaign board",
  "cx.why.h": "Why it matters",
  "cx.why.res.h": "For residents",
  "cx.why.res": "A warning about scams that are active right now, before you click anything.",
  "cx.why.auth.h": "For authorities",
  "cx.why.auth": "Ready to connect, not connected. One campaign view instead of hundreds of single reports, earlier takedown requests, and shareable as STIX intelligence.",
  "cx.why.safe.h": "Speed without risk",
  "cx.why.safe": "The Sentinel prepares takedown and police-report drafts. Nothing leaves the system until an officer approves it.",
  "cx.how.h": "How a campaign is built",
  "cx.how.1": "Checks and reports arrive.",
  "cx.how.2": "The Sentinel links them by shared fingerprints: brand, page kit, domain pattern and timing.",
  "cx.how.3": "Fixed rules, not the AI, decide that it is a campaign.",
  "cx.how.4": "The AI writes a bilingual summary, and drafts wait for human approval.",
  "cx.read.h": "How to read a card",
  "cx.read.title": "Title: the campaign name and the brand it imitates.",
  "cx.read.count": "Linked checks: how many checks the Sentinel has put into this campaign.",
  "cx.read.seen": "Last seen: when the most recent linked check arrived.",
  "cx.read.sev": "Severity: critical, high, medium or low. A shape goes with the word, so meaning never depends on colour.",
  "cx.read.bars": "Small bars: the campaign's activity over recent periods. The last bar is the newest.",
  "cx.read.source": "A \"Synthetic data\" or \"Replay\" label: this card is not a live report.",
  "cx.read.advice": "Last line: what we advise right now.",
  "cx.note": "Domains are shown defanged, like example[.]com, so they cannot be clicked by mistake. Data on this demo is replayed or synthetic wherever it is labelled so.",
  "cx.more": "Technical detail on the agents page",
};

export type CxKey = keyof typeof ar;
export const CX_MESSAGES: Record<Lang, Record<CxKey, string>> = { ar, en };
export const cx = (lang: Lang, key: CxKey): string => CX_MESSAGES[lang][key];
