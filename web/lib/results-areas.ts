/**
 * The per-area evaluation results (faithfulness, stability, route comparison, cost, sandbox, brand-new pages, T3,
 * synthetic split, message text, red-team, Arabic clarity, fits), bundled by scripts/eval-areas.mjs into
 * lib/eval-areas.generated.json. This module only labels and formats: every number rendered comes from a bundled row
 * (value, k, n, 95% range). Labels and caveats here are plain text with no figures in them.
 */
import raw from "./eval-areas.generated.json";
import type { Lang } from "./contracts";

export type RowKind = "rate" | "count" | "usd" | "num";
export interface AreaRow {
  kind: RowKind;
  value: number;
  k: number | null;
  n: number | null;
  lo: number | null;
  hi: number | null;
}
export interface Area {
  id: string;
  artifact: string;
  date: string;
  provenance: string;
  route: string;
  model: string;
  caveat: string;
  rows: Record<string, AreaRow>;
  notEvaluated: string[];
  renderArtifact?: string;
  runs?: { artifact: string; budget: string; date: string }[];
}

type Bilingual = { ar: string; en: string };
interface AreaCopy {
  title: Bilingual;
  scope: Bilingual;
  /** Numberless caveat shown beside the figures. */
  note?: Bilingual;
  rows: Record<string, Bilingual>;
}

const COPY: Record<string, AreaCopy> = {
  redteam: {
    title: { ar: "مقاومة حقن التعليمات (الفريق الأحمر)", en: "Prompt-injection resistance (red team)" },
    scope: { ar: "حالات هجوم اصطناعية عبر مسار الفحص المُشحون بالنموذج المحلي. يُقرأ عدد الحالات الضارة دائماً مع عدد ما أجاب عنه النموذج فعلاً.", en: "Synthetic attack cases through the shipped cascade on the local model. The harmful count is always read together with how many cases the model actually answered." },
    note: { ar: "عند المهلة الإنتاجية القصيرة لم يُجب النموذج عن معظم الحالات، فهذا القياس لا يغطي طبقة النموذج هناك. أُصلحت لاحقاً الحالة الوحيدة الفاشلة في الشيفرة، والرقم المعروض هو ما نُشر ولم يُعَد تشغيله.", en: "At the short production deadline the model answered most cases not at all, so that run does not cover the model layer. The one failing case was fixed in code afterwards; the figure shown is as published and has not been re-run." },
    rows: {
      extended_harmful: { ar: "حالات ضارة (مهلة ممتدة)", en: "Harmful cases (extended deadline)" },
      extended_answered: { ar: "حالات أجاب عنها النموذج (مهلة ممتدة)", en: "Cases the model answered (extended deadline)" },
      production_harmful: { ar: "حالات ضارة (مهلة إنتاجية)", en: "Harmful cases (production deadline)" },
      production_answered: { ar: "حالات أجاب عنها النموذج (مهلة إنتاجية)", en: "Cases the model answered (production deadline)" },
    },
  },
  faithfulness: {
    title: { ar: "أمانة الأسباب للأدلة", en: "Faithfulness of reasons to evidence" },
    scope: { ar: "أسباب الحكم القائمة على قوالب مقابل الأدلة، وملخصات Sentinel المولَّدة بالنموذج بعد تدقيق المُحقِّق.", en: "Template-based verdict reasons against the evidence, and Sentinel summaries written by a model after the verifier's check." },
    note: { ar: "بيانات اصطناعية؛ حالات صغيرة العدد ونطاقاتها واسعة.", en: "Synthetic data; small counts with wide ranges." },
    rows: {
      reasons_faithful: { ar: "أسباب مطابقة للأدلة", en: "Reasons that match the evidence" },
      verdicts_fully_faithful: { ar: "أحكام كل أسبابها مطابقة", en: "Verdicts whose reasons all match" },
      sentinel_cloud_claims_kept: { ar: "ادعاءات أبقاها المُحقِّق (السحابي)", en: "Claims kept by the verifier (cloud)" },
      sentinel_cloud_kept_cite_valid: { ar: "ادعاءات مُبقاة تستشهد بدليل صحيح (السحابي)", en: "Kept claims citing valid evidence (cloud)" },
      sentinel_local_claims_kept: { ar: "ادعاءات أبقاها المُحقِّق (المحلي)", en: "Claims kept by the verifier (local)" },
      sentinel_local_kept_cite_valid: { ar: "ادعاءات مُبقاة تستشهد بدليل صحيح (المحلي)", en: "Kept claims citing valid evidence (local)" },
    },
  },
  stability: {
    title: { ar: "ثبات الحكم عند التكرار", en: "Verdict stability across repeats" },
    scope: { ar: "ثلاث مرات لكل مدخل على أمثلة اصطناعية، مع الذكاء الاصطناعي وبدونه.", en: "Three runs per input on synthetic fixtures, with and without the AI layers." },
    note: { ar: "الأمثلة التي لم تكتمل فيها المرات الثلاث عُدَّت فاشلة ولم تُخفَ؛ والنموذج المحلي يشارك وحدة المعالجة مع أعمال أخرى.", en: "Items whose three runs did not all complete are counted, not hidden; the local model shared its GPU with other jobs." },
    rows: {
      ai_on_all_three_identical: { ar: "ثبات التصنيف في المرات الثلاث (مع الذكاء الاصطناعي)", en: "Same label in all three runs (AI on)" },
      ai_on_among_completed: { ar: "الثبات بين الأمثلة المكتملة (مع الذكاء الاصطناعي)", en: "Same label among items that completed (AI on)" },
      ai_off_all_three_identical: { ar: "ثبات التصنيف (بدون الذكاء الاصطناعي)", en: "Same label in all three runs (AI off)" },
    },
  },
  route_compare: {
    title: { ar: "المسار السحابي والمسار السيادي", en: "Cloud route and sovereign route" },
    scope: { ar: "المدخلات الاصطناعية نفسها عبر المسارين.", en: "The same synthetic inputs through both routes." },
    note: { ar: "التسميات من وضع المؤلف قبل تشغيل أي نموذج، والعينة صغيرة.", en: "Labels were set by the author before any model ran; the sample is small." },
    rows: {
      exact_label_agreement: { ar: "اتفاق التصنيف بين المسارين", en: "Label agreement between routes" },
      cloud_recall_warning: { ar: "تنبيه على الصفحات الاحتيالية (السحابي)", en: "Warned on phishing fixtures (cloud)" },
      local_recall_warning: { ar: "تنبيه على الصفحات الاحتيالية (المحلي)", en: "Warned on phishing fixtures (local)" },
      cloud_benign_warning: { ar: "تنبيه على أمثلة سليمة (السحابي)", en: "Warned on benign fixtures (cloud)" },
      local_benign_warning: { ar: "تنبيه على أمثلة سليمة (المحلي)", en: "Warned on benign fixtures (local)" },
    },
  },
  cost_per_check: {
    title: { ar: "كلفة الفحص الواحد", en: "Cost per check" },
    scope: { ar: "كلفة الذكاء الاصطناعي من الرموز المستخدمة فعلاً على أمثلة اصطناعية قصيرة؛ المسار المحلي بلا كلفة واجهة إضافية.", en: "AI cost from tokens actually used on short synthetic fixtures; the local route has no marginal API cost." },
    note: { ar: "لا تشمل البنية التحتية. المسار المحلي ليس بلا كلفة، بل بلا كلفة واجهة إضافية.", en: "Excludes infrastructure. Local is zero marginal API cost, not zero cost." },
    rows: {
      cloud_usd_per_check: { ar: "متوسط الكلفة للفحص (السحابي، دولار)", en: "Mean cost per check (cloud, USD)" },
      cloud_usd_per_1000: { ar: "الكلفة لكل ألف فحص (السحابي، دولار)", en: "Cost per thousand checks (cloud, USD)" },
      cloud_usd_p95: { ar: "الكلفة عند الشريحة المئوية الخامسة والتسعين (السحابي، دولار)", en: "Cost at the ninety-fifth percentile (cloud, USD)" },
      local_usd_per_check: { ar: "كلفة الواجهة الإضافية (المحلي، دولار)", en: "Marginal API cost (local, USD)" },
    },
  },
  sandbox_t2: {
    title: { ar: "مرحلة الزيارة المعزولة", en: "Sandboxed visit tier" },
    scope: { ar: "سلامة التصيير على مواقع حقيقية مشروعة محجوبة، ومساهمة المرحلة على أمثلة اصطناعية.", en: "Render health on held-out legitimate real sites, and the tier's contribution on synthetic fixtures." },
    note: { ar: "لم نقس استدعاء المرحلة على صفحات احتيالية حقيقية، ولا نزور صفحات احتيالية حية.", en: "Recall on real phishing pages is not measured, and we do not visit live phishing pages." },
    rows: {
      render_reached_of_web: { ar: "مواقع وصلت إليها المرحلة (من المواقع التي تقدم صفحة)", en: "Web sites the tier reached" },
      render_clean_of_attempted: { ar: "تصيير سليم (من المحاولات)", en: "Clean render (of attempts)" },
      render_degraded_of_attempted: { ar: "تصيير متعذّر (من المحاولات)", en: "Render unavailable (of attempts)" },
      fixture_dangerous_after_t1: { ar: "خطِر بعد تحليل العنوان (أمثلة اصطناعية)", en: "Dangerous after address analysis (fixtures)" },
      fixture_dangerous_after_t2: { ar: "خطِر بعد الزيارة المعزولة (أمثلة اصطناعية)", en: "Dangerous after sandbox visit (fixtures)" },
    },
  },
  brand_new_pages: {
    title: { ar: "صفحات جديدة كلياً على مواقع لم تُرَ", en: "Brand-new pages on never-seen hosts" },
    scope: { ar: "صفحات تحاكي بنكاً وهمياً مخترَعاً على نطاقات اختبار محجوزة، دون الذكاء الاصطناعي.", en: "Pages imitating an invented demo bank on reserved test hosts, AI layers off." },
    note: { ar: "نطاقات الاختبار ترفع الاشتباه المبدئي حتى للصفحات السليمة، فتُقرأ نسب التنبيه مع صف الضبط السليم، ويُعدّ «خطِر» هو المقياس المميِّز.", en: "Test hosts raise the starting suspicion even for benign pages, so read warning rates with the benign-control row; 'dangerous' is the discriminating figure." },
    rows: {
      lookalike_dangerous: { ar: "صفحات منتحلة صُنِّفت خطِرة", en: "Lookalike pages rated dangerous" },
      generic_warning: { ar: "صفحات طلب بيانات عامة نُبّه عليها", en: "Generic credential pages warned" },
      benign_warning: { ar: "صفحات سليمة نُبّه عليها (ضبط)", en: "Benign controls warned" },
      benign_dangerous: { ar: "صفحات سليمة صُنِّفت خطِرة (ضبط)", en: "Benign controls rated dangerous" },
    },
  },
  t3_investigator: {
    title: { ar: "النظرة الثانية بالذكاء الاصطناعي (المحقِّق)", en: "AI second look (investigator)" },
    scope: { ar: "سلوك المحقِّق على أمثلة تصل فعلاً إلى النطاق غير المحسوم؛ أدوات الشبكة معطّلة في هذا التشغيل.", en: "Investigator behaviour on fixtures that really reach the uncertain band; network tools were off in this run." },
    note: { ar: "يقيس الالتزام بالحدود والتتبّع لا قيمة الأدلة الحية.", en: "Measures adherence to limits and provenance, not the value of live evidence." },
    rows: {
      cloud_reached_t3: { ar: "فحوص وصلت إلى المحقِّق (السحابي)", en: "Checks that reached the investigator (cloud)" },
      cloud_label_changed: { ar: "تغيّر التصنيف بفعل المحقِّق (السحابي)", en: "Label changed by the investigator (cloud)" },
      cloud_forbidden_tool: { ar: "استدعاء أداة محظورة (السحابي)", en: "Forbidden tool call (cloud)" },
      local_reached_t3: { ar: "فحوص وصلت إلى المحقِّق (المحلي)", en: "Checks that reached the investigator (local)" },
      local_label_changed: { ar: "تغيّر التصنيف بفعل المحقِّق (المحلي)", en: "Label changed by the investigator (local)" },
      local_forbidden_tool: { ar: "استدعاء أداة محظورة (المحلي)", en: "Forbidden tool call (local)" },
    },
  },
  synthetic_split: {
    title: { ar: "البيانات الحقيقية والاصطناعية منفصلتين", en: "Real and synthetic data, kept apart" },
    scope: { ar: "تحليل العنوان مع المحكّم والرسائل النصية دون اتصال، دون نموذج ودون مرحلة الصفحة. لا تُجمع الأرقام الحقيقية والاصطناعية.", en: "Address analysis with the arbiter and message text, offline, no model and no page tier. Real and synthetic figures are never pooled." },
    note: { ar: "نطاقات الاختبار المحجوزة ترفع نسبة التنبيه على الأمثلة السليمة الاصطناعية؛ فهي حدّ أعلى لا نسبة ميدانية.", en: "Reserved test hosts raise the warning rate on synthetic benign items; read it as an upper bound, not a field rate." },
    rows: {
      real_test_recall_warning: { ar: "حقيقي: احتيال نُبّه عليه (اختبار)", en: "Real: scams warned (test)" },
      real_test_fpr_warning: { ar: "حقيقي: سليم نُبّه عليه خطأً (اختبار)", en: "Real: legitimate wrongly warned (test)" },
      synthetic_url_recall_warning: { ar: "اصطناعي (روابط): احتيال نُبّه عليه", en: "Synthetic URLs: scams warned" },
      synthetic_url_fpr_warning: { ar: "اصطناعي (روابط): سليم نُبّه عليه", en: "Synthetic URLs: benign warned" },
      synthetic_message_recall_warning: { ar: "اصطناعي (رسائل): احتيال نُبّه عليه", en: "Synthetic messages: scams warned" },
      synthetic_message_fpr_warning: { ar: "اصطناعي (رسائل): سليم نُبّه عليه", en: "Synthetic messages: benign warned" },
    },
  },
  message_text: {
    title: { ar: "فحص نص الرسائل", en: "Message-text check" },
    scope: { ar: "رسائل اصطناعية بلا روابط بأربع لهجات وكتابات؛ كاتب واحد ودُقِّقت من المشرف. قراءة الاختبار الأخيرة منشورة.", en: "Synthetic link-free messages in four language styles; single author, supervisor-audited. The latest test read is published." },
    note: { ar: "العينة صغيرة والنطاقات عريضة، وليست ضماناً على رسائل حقيقية.", en: "A small sample with wide ranges; not a guarantee on real messages." },
    rows: {
      test_recall: { ar: "رسائل احتيالية نُبّه عليها (اختبار)", en: "Scam messages warned (test)" },
      test_fpr: { ar: "رسائل سليمة نُبّه عليها خطأً (اختبار)", en: "Legitimate messages wrongly warned (test)" },
      test_rules_only_recall: { ar: "القواعد وحدها، قبل النموذج (اختبار)", en: "Rules only, before the model (test)" },
      val_recall: { ar: "رسائل احتيالية نُبّه عليها (تحقق)", en: "Scam messages warned (validation)" },
      val_fpr: { ar: "رسائل سليمة نُبّه عليها خطأً (تحقق)", en: "Legitimate messages wrongly warned (validation)" },
    },
  },
  arabic_clarity: {
    title: { ar: "وضوح النص العربي", en: "Arabic text clarity" },
    scope: { ar: "فحوص آلية لملاءمة الشاشة الصغيرة على نصوص القوالب. تقييم الفهم والوضوح من قارئ عربي ما زال معلّقاً.", en: "Automated phone-fit checks on the template texts. The native-speaker comprehension rating is still pending." },
    rows: {
      action_sentences_within_budget: { ar: "جمل الإجراء ضمن حدّ الشاشة", en: "Action sentences within the phone budget" },
      reasons_within_budget: { ar: "الأسباب ضمن حدّ الشاشة", en: "Reasons within the phone budget" },
      items: { ar: "عدد الأمثلة في ورقة التقييم", en: "Items on the rating sheet" },
    },
  },
  fit_message_weight: {
    title: { ar: "المعايرة: وزن نية الاحتيال في الرسائل", en: "Fit: message scam-intent weight" },
    scope: { ar: "وزن اختير على مجموعة التحقق الاصطناعية بحيث تعظَّم الاستدعاء بإنذار خاطئ لا يتجاوز الحدّ.", en: "A weight chosen on the synthetic validation set to maximise recall within the false-alarm limit." },
    rows: {
      weight: { ar: "الوزن المختار", en: "Chosen weight" },
      val_recall: { ar: "الاستدعاء على التحقق", en: "Validation recall" },
      val_fpr: { ar: "الإنذار الخاطئ على التحقق", en: "Validation false-alarm rate" },
    },
  },
  fit_model_cap: {
    title: { ar: "المعايرة: سقف حكم النموذج", en: "Fit: model verdict cap" },
    scope: { ar: "معاملان اختيرا على مجموعة التحقق فقط، لا على الاختبار.", en: "Two parameters chosen on the validation set only, never on the test set." },
    rows: {
      margin: { ar: "الهامش", en: "Margin" },
      strong_adj: { ar: "تعديل الإشارة القوية", en: "Strong-signal adjustment" },
    },
  },
};

/** Order the areas appear on the page. */
export const AREA_ORDER = ["redteam", "faithfulness", "stability", "route_compare", "t3_investigator", "sandbox_t2", "brand_new_pages", "synthetic_split", "message_text", "cost_per_check", "arabic_clarity", "fit_message_weight", "fit_model_cap"] as const;

/** Keys of the main artifact's `not_evaluated` list that an area now measures (so they leave the "not measured" chips). */
export const MEASURED_NE: Record<string, string> = {
  cost_per_check_llm: "cost_per_check",
  faithfulness: "faithfulness",
  flip_rate_3_runs: "stability",
  injection_attack_success_rate: "redteam",
  llm_tier_T3: "t3_investigator",
  sandbox_tier_T2: "sandbox_t2",
  zero_day: "brand_new_pages",
  arabic_clarity: "arabic_clarity",
  synthetic: "synthetic_split",
  cloud_route: "route_compare",
  sovereign_route: "route_compare",
};

const PENDING: Record<string, Bilingual> = {
  phishing_side_t2_recall: { ar: "استدعاء مرحلة الزيارة المعزولة على صفحات احتيالية: لم يُقَس (يلزمه صفحات مصنّفة، ولا نزور صفحات احتيالية حية)", en: "Sandbox-tier recall on phishing pages: not evaluated (needs labelled pages; we do not visit live phishing pages)" },
  human_rating: { ar: "وضوح العربية بتقييم قارئ عربي: قيد الانتظار (ورقة التقييم جاهزة ولم تُملأ)", en: "Arabic clarity by a native-speaker rating: pending (the rating sheet is ready, not yet filled in)" },
  energy: { ar: "طاقة التشغيل المحلي: لم تُقَس", en: "Energy of the local route: not evaluated" },
};

const LABELS = {
  ar: { artifact: "ملف التقييم", date: "التاريخ", provenance: "مصدر البيانات", route: "المسار", model: "النموذج", caveat: "تنبيه", asPublished: "نص التنبيه كما نُشر", of: "من", ci: "نطاق الثقة 95%", measured: "نتائج القياس بحسب المحور", measuredLead: "كل رقم هنا منقول من ملف التقييم المنشور لكل محور، مع نطاقه ومصدره وتنبيهه.", pendingTitle: "ما زال قيد القياس" },
  en: { artifact: "Artifact", date: "Date", provenance: "Data provenance", route: "Route", model: "Model", caveat: "Caveat", asPublished: "Caveat as published", of: "of", ci: "95% range", measured: "Measured results by area", measuredLead: "Every figure here is copied from that area's published evaluation file, with its range, source and caveat.", pendingTitle: "Still not measured" },
} as const;
export const areaLabels = (lang: Lang) => LABELS[lang];

type Loose = Record<string, unknown>;
const finite = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

export function parseAreas(file: unknown): Area[] {
  const f = file as { available?: boolean; areas?: Record<string, Loose> } | null;
  if (!f || f.available !== true || !f.areas) return [];
  const out: Area[] = [];
  for (const id of AREA_ORDER) {
    const a = f.areas[id];
    if (!a || !COPY[id]) continue;
    const rows: Record<string, AreaRow> = {};
    for (const key of Object.keys(COPY[id].rows)) {
      const r = (a.rows as Record<string, Loose> | undefined)?.[key];
      const value = finite(r?.value);
      if (!r || value === null) continue;
      rows[key] = { kind: r.kind as RowKind, value, k: finite(r.k), n: finite(r.n), lo: finite(r.lo), hi: finite(r.hi) };
    }
    if (Object.keys(rows).length === 0) continue;
    out.push({
      id,
      artifact: String(a.artifact ?? ""),
      date: String(a.date ?? ""),
      provenance: String(a.provenance ?? ""),
      route: String(a.route ?? ""),
      model: String(a.model ?? ""),
      caveat: String(a.caveat ?? ""),
      rows,
      notEvaluated: Array.isArray(a.notEvaluated) ? a.notEvaluated.filter((x): x is string => typeof x === "string") : [],
      renderArtifact: typeof a.renderArtifact === "string" ? a.renderArtifact : undefined,
      runs: Array.isArray(a.runs) ? (a.runs as Area["runs"]) : undefined,
    });
  }
  return out;
}

export const loadAreas = (): Area[] => parseAreas(raw);

export const areaTitle = (id: string, lang: Lang): string => COPY[id]?.title[lang] ?? id;
export const areaScope = (id: string, lang: Lang): string => COPY[id]?.scope[lang] ?? "";
export const areaNote = (id: string, lang: Lang): string => COPY[id]?.note?.[lang] ?? "";
export const rowLabel = (id: string, key: string, lang: Lang): string => COPY[id]?.rows[key]?.[lang] ?? key;
export const pendingLabel = (key: string, lang: Lang): string => PENDING[key]?.[lang] ?? key;

const locale = (lang: Lang) => (lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB");
const pct = (v: number, lang: Lang) => `${(v * 100).toLocaleString(locale(lang), { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
const plain = (v: number, lang: Lang) => v.toLocaleString(locale(lang), { maximumFractionDigits: 6 });

export interface RowText {
  main: string;
  detail: string;
  ci: string;
}

/** The only place a row becomes visible text. Every digit comes from the row's own fields. */
export function rowText(row: AreaRow, lang: Lang): RowText {
  const of = LABELS[lang].of;
  switch (row.kind) {
    case "rate": {
      const detail = row.k !== null && row.n !== null ? `${row.k} ${of} ${row.n}` : row.n !== null ? `n = ${row.n}` : "";
      const ci = row.lo !== null && row.hi !== null ? `${pct(row.lo, lang)} – ${pct(row.hi, lang)}` : "";
      return { main: pct(row.value, lang), detail, ci };
    }
    case "count":
      return { main: plain(row.value, lang), detail: row.n !== null ? `${of} ${row.n}` : "", ci: "" };
    case "usd": {
      const ci = row.lo !== null && row.hi !== null ? `$${plain(row.lo, lang)} – $${plain(row.hi, lang)}` : "";
      return { main: `$${plain(row.value, lang)}`, detail: row.n !== null ? `n = ${row.n}` : "", ci };
    }
    case "num":
      return { main: plain(row.value, lang), detail: row.n !== null ? `n = ${row.n}` : "", ci: "" };
  }
}

/** Keys still shown as "not measured": the main artifact's own list minus what an area now measures, plus each area's own pending items. */
export function pendingKeys(mainNotEvaluated: string[], areas: Area[]): { main: string[]; extra: string[] } {
  const have = new Set(areas.map((a) => a.id));
  return {
    main: mainNotEvaluated.filter((k) => !(MEASURED_NE[k] && have.has(MEASURED_NE[k]))),
    extra: areas.flatMap((a) => a.notEvaluated).filter((k) => k in PENDING),
  };
}
