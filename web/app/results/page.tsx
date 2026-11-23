import type { Metadata } from "next";
import { loadCapabilities } from "@/lib/capabilities";
import { Icon } from "@/components/Icon";
import type { Lang } from "@/lib/contracts";
import { pageMetadata } from "@/lib/meta";
import { formatCi, formatMetric, loadResults, type SplitView } from "@/lib/results";
import { serverLang } from "@/lib/server-lang";

type Copy = {
  title: string;
  lead: string;
  pending: string;
  pendingBody: string;
  test: string;
  val: string;
  sample: string;
  ci: string;
  official: string;
  officialNote: string;
  scopeTitle: string;
  scope: (r: { temporalCut: boolean; n: number | null }) => string;
  caveat: string;
  provenance: string;
  artifact: string;
  date: string;
  dataset: string;
  scopeRaw: string;
  commit: string;
  dirty: string;
  draft: string;
  notEvalTitle: string;
  notEvalLead: string;
  metrics: Record<string, string>;
  notEval: Record<string, string>;
};

const COPY: Record<Lang, Copy> = {
  ar: {
    title: "نتائج التقييم",
    lead: "كل رقم في هذه الصفحة منقول آلياً من ملف التقييم المنشور، ولا يُكتب يدوياً. تُعرض مع كل مقياس فترة ثقة 95%.",
    pending: "التقييم قيد الإنجاز",
    pendingBody: "لم يُنشر بعد ملف تقييم يمكن عرضه. ستظهر النتائج هنا فور نشره، ولن نعرض أي رقم قبل ذلك.",
    test: "مجموعة الاختبار المحجوبة",
    val: "مجموعة التحقق",
    sample: "عدد الأمثلة",
    ci: "فترة ثقة 95%",
    official: "مواقع رسمية صُنّفت خطأً بأنها خطِرة",
    officialNote: "العدد المطلق في هذه المجموعة.",
    scopeTitle: "نطاق القياس",
    scope: ({ temporalCut }) => `يقيس هذا التقييم طبقة النموذج الإحصائي للعناوين (T1) مع المحكّم الحتمي، دون الاتصال بالشبكة، على بيانات حقيقية فقط. ${temporalCut ? "قُسّمت البيانات زمنياً." : "لم تُقسَّم البيانات زمنياً، إذ جُمعت في سحبة واحدة."}`,
    caveat: "عيّنة صغيرة نسبياً، ولذلك فترات الثقة عريضة. النتائج مقياس لأداء النموذج على بيانات مشابهة لبيانات التدريب، وليست ضماناً أمام حملات جديدة كلياً.",
    provenance: "مصدر الأرقام",
    artifact: "ملف التقييم",
    date: "تاريخ الإنشاء (UTC)",
    dataset: "بصمة مجموعة البيانات",
    scopeRaw: "النطاق كما ورد في الملف",
    commit: "إصدار الشيفرة (git)",
    dirty: "بُني من نسخة عمل غير مثبَّتة بالكامل (غير نظيفة).",
    draft: "الخدمة الحية تستخدم حالياً المصنّف المبدئي؛ النموذج المقيس (T1) يُربط في PR #47. الأرقام أعلاه تخص النموذج المقيس.",
    notEvalTitle: "لم يُقَس بعد",
    notEvalLead: "هذه الجوانب لم تُقيَّم في الملف المنشور، ولذلك لا نذكر لها أي رقم.",
    metrics: { precision: "الدقة (Precision)", recall: "الاستدعاء (Recall)", f1: "مقياس F1", fpr: "معدل الإنذار الخاطئ", pr_auc: "المساحة تحت منحنى PR", ece: "خطأ المعايرة (ECE)" },
    notEval: {
      arabic_clarity: "وضوح الصياغة العربية",
      cost_per_check_llm: "كلفة الفحص بالنموذج اللغوي",
      faithfulness: "أمانة التعليل للأدلة",
      flip_rate_3_runs: "ثبات الحكم عبر ثلاث تشغيلات",
      injection_attack_success_rate: "نجاح هجمات الحقن",
      llm_tier_T3: "طبقة المحقّق (T3)",
      sandbox_tier_T2: "طبقة الزيارة المعزولة (T2)",
      zero_day: "الحملات الجديدة كلياً",
      synthetic: "البيانات الاصطناعية",
      cloud_route: "المسار السحابي",
      sovereign_route: "المسار السيادي",
    },
  },
  en: {
    title: "Evaluation results",
    lead: "Every number on this page is copied automatically from the published evaluation artifact, never typed by hand. Each metric is shown with its 95% confidence interval.",
    pending: "Evaluation in progress",
    pendingBody: "No evaluation artifact has been published yet. Results will appear here as soon as one is, and no figure is shown before then.",
    test: "Held-out test set",
    val: "Validation set",
    sample: "Examples",
    ci: "95% confidence interval",
    official: "Official sites wrongly rated dangerous",
    officialNote: "Absolute count in this set.",
    scopeTitle: "Scope of the measurement",
    scope: ({ temporalCut }) => `This evaluation measures the statistical address model (T1) together with the deterministic arbiter, offline, on real data only. ${temporalCut ? "The data was split by time." : "The data was not split by time, as it was collected in a single pull."}`,
    caveat: "The sample is fairly small, so the confidence intervals are wide. The results measure performance on data similar to the training data. They are not a guarantee against entirely new campaigns.",
    provenance: "Where the numbers come from",
    artifact: "Evaluation artifact",
    date: "Created (UTC)",
    dataset: "Dataset hash",
    scopeRaw: "Scope as recorded in the artifact",
    commit: "Code revision (git)",
    dirty: "Built from a working tree with uncommitted changes.",
    draft: "The live service currently uses the draft classifier; the measured T1 model is wired in PR #47. The figures above describe the measured model.",
    notEvalTitle: "Not yet evaluated",
    notEvalLead: "These aspects were not evaluated in the published artifact, so we state no figure for them.",
    metrics: { precision: "Precision", recall: "Recall", f1: "F1 score", fpr: "False-alarm rate", pr_auc: "Area under the PR curve", ece: "Calibration error (ECE)" },
    notEval: {
      arabic_clarity: "Arabic wording clarity",
      cost_per_check_llm: "Cost per check with the language model",
      faithfulness: "Faithfulness of reasons to evidence",
      flip_rate_3_runs: "Verdict stability across three runs",
      injection_attack_success_rate: "Injection attack success rate",
      llm_tier_T3: "Investigator tier (T3)",
      sandbox_tier_T2: "Isolated-visit tier (T2)",
      zero_day: "Entirely new campaigns",
      synthetic: "Synthetic data",
      cloud_route: "Cloud route",
      sovereign_route: "Sovereign route",
    },
  },
};

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: COPY[lang].title, description: COPY[lang].lead });
}

function SplitBlock({ view, lang, c }: { view: SplitView; lang: Lang; c: Copy }) {
  const id = `split-${view.split}`;
  return (
    <section aria-labelledby={id} data-testid={id}>
      <div className="sec-head">
        <h2 id={id}>{view.split === "test" ? c.test : c.val}</h2>
        <span className="chip">{c.sample}: <span className="mono">{view.n}</span></span>
      </div>
      <div className="metrics">
        {view.rows.map((r) => (
          <div className="card metric" key={r.key} data-testid={`metric-${view.split}-${r.key}`}>
            <span className="lbl">{c.metrics[r.key] ?? r.key}</span>
            <b>{formatMetric(r.key, r.value, lang)}</b>
            {r.lo !== null ? <span className="ci" title={c.ci}>{c.ci}: {formatCi(r, lang)}</span> : null}
          </div>
        ))}
        {view.officialFalseDangerous !== null ? (
          <div className="card metric" data-testid={`metric-${view.split}-official`}>
            <span className="lbl">{c.official}</span>
            <b>{view.officialFalseDangerous}</b>
            <span className="ci">{c.officialNote}</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export default async function ResultsPage() {
  const lang = await serverLang();
  const c = COPY[lang];
  const r = loadResults();
  const caps = await loadCapabilities();
  const testN = r?.splits.find((s) => s.split === "test")?.n ?? null;
  return (
    <main id="main" className="page">
      <div className="wrap">
        <h1 className="page-title">{c.title}</h1>
        <p className="page-lead">{c.lead}</p>

        {!r ? (
          <div className="card state" role="status" data-testid="results-pending">
            <Icon name="clock" size={32} />
            <h2 className="h3">{c.pending}</h2>
            <p className="muted">{c.pendingBody}</p>
          </div>
        ) : (
          <>
            {r.splits.map((s) => <SplitBlock key={s.split} view={s} lang={lang} c={c} />)}

            {!caps.t1_measured_model ? (
              <p className="card callout" role="note" data-testid="draft-classifier">
                <Icon name="clock" size={24} />
                <span>{c.draft}</span>
              </p>
            ) : null}

            <section className="prose" aria-labelledby="scope-h">
              <h2 id="scope-h">{c.scopeTitle}</h2>
              <p>{c.scope({ temporalCut: r.temporalCut, n: testN })}</p>
              <p className="card callout" role="note">
                <Icon name="scale" size={24} />
                <span>{c.caveat}</span>
              </p>
            </section>

            {r.notEvaluated.length > 0 ? (
              <section className="prose" aria-labelledby="ne-h" data-testid="not-evaluated">
                <h2 id="ne-h">{c.notEvalTitle}</h2>
                <p>{c.notEvalLead}</p>
                <ul className="chips">
                  {r.notEvaluated.map((k) => <li className="chip" key={k}>{c.notEval[k] ?? k}</li>)}
                </ul>
              </section>
            ) : null}

            <section className="prose" aria-labelledby="prov-h">
              <h2 id="prov-h">{c.provenance}</h2>
              <ul>
                <li>{c.artifact}: <code>{r.artifact}</code></li>
                <li>{c.date}: <code>{r.createdAt}</code></li>
                <li>{c.dataset}: <code>{r.datasetHash.slice(0, 16)}</code></li>
                <li>{c.scopeRaw}: <code>{r.scope}</code></li>
                <li>{c.commit}: <code>{r.gitSha}</code>{r.gitSha.endsWith("-dirty") ? <> {c.dirty}</> : null}</li>
              </ul>
            </section>
          </>
        )}
      </div>
    </main>
  );
}
