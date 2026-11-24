import type { Metadata } from "next";
import Link from "next/link";
import { ProofStats } from "@/components/ProofStats";
import { loadCapabilities } from "@/lib/capabilities";
import { Icon } from "@/components/Icon";
import type { Lang } from "@/lib/contracts";
import { translate, translateMaybe, type MessageKey } from "@/lib/i18n";
import { pageMetadata } from "@/lib/meta";
import { formatCi, formatMetric, loadResults, type SplitView } from "@/lib/results";
import { areaLabels, areaNote, areaScope, areaTitle, loadAreas, pendingKeys, pendingLabel, rowLabel, rowText, type Area } from "@/lib/results-areas";
import { serverLang } from "@/lib/server-lang";

/** Page-local copy for the states v2's shared copy does not cover. Plain text, no numbers. */
const LOCAL: Record<Lang, { pending: string; pendingBody: string; draft: string; scopeRaw: string; commit: string; dirty: string }> = {
  ar: {
    pending: "التقييم قيد الإنجاز",
    pendingBody: "لم يُنشر بعد ملف تقييم يمكن عرضه. ستظهر النتائج هنا فور نشره، ولن نعرض أي رقم قبل ذلك.",
    draft: "الخدمة الحية تستخدم حالياً المصنّف المبدئي؛ النموذج المقيس لتحليل العنوان لم يُربط بها بعد. الأرقام أعلاه تخص النموذج المقيس.",
    scopeRaw: "النطاق كما ورد في الملف",
    commit: "إصدار الشيفرة (git)",
    dirty: "بُني من نسخة عمل غير مثبَّتة بالكامل (غير نظيفة).",
  },
  en: {
    pending: "Evaluation in progress",
    pendingBody: "No evaluation artifact has been published yet. Results will appear here as soon as one is, and no figure is shown before then.",
    draft: "The live service currently uses the draft classifier; the measured address-analysis model is not wired into it yet. The figures above describe the measured model.",
    scopeRaw: "Scope as recorded in the artifact",
    commit: "Code revision (git)",
    dirty: "Built from a working tree with uncommitted changes.",
  },
};

export async function generateMetadata(): Promise<Metadata> {
  const lang = await serverLang();
  return pageMetadata(lang, { title: translate(lang, "results.title"), description: translate(lang, "results.lead") });
}

function SplitBlock({ view, lang }: { view: SplitView; lang: Lang }) {
  const t = (key: MessageKey, vars?: Record<string, string | number>) => translate(lang, key, vars);
  const id = `split-${view.split}`;
  return (
    <section aria-labelledby={id} data-testid={id}>
      <div className="sec-head">
        <h3 id={id} className="h3">{t(view.split === "test" ? "results.split.test" : "results.split.val")}</h3>
        <span className="chip">{t("results.n", { n: view.n })}</span>
      </div>
      <div className="metrics">
        {view.rows.map((r) => (
          <div className="card metric" key={r.key} data-testid={`metric-${view.split}-${r.key}`}>
            <span className="lbl">{t(`metric.${r.key}` as MessageKey)}</span>
            <b>{formatMetric(r.key, r.value, lang)}</b>
            {r.lo !== null ? <span className="ci">{t("proof.ci")}: {formatCi(r, lang)}</span> : null}
          </div>
        ))}
        {view.officialFalseDangerous !== null ? (
          <div className="card metric" data-testid={`metric-${view.split}-official`}>
            <span className="lbl">{t("proof.official")}</span>
            <b>{view.officialFalseDangerous}</b>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function AreaBlock({ area, lang }: { area: Area; lang: Lang }) {
  const L = areaLabels(lang);
  const id = `area-${area.id}`;
  const note = areaNote(area.id, lang);
  return (
    <section aria-labelledby={id} data-testid={id} className="area">
      <h3 id={id} className="h3">{areaTitle(area.id, lang)}</h3>
      <p className="muted">{areaScope(area.id, lang)}</p>
      <div className="metrics">
        {Object.entries(area.rows).map(([key, row]) => {
          const x = rowText(row, lang);
          return (
            <div className="card metric" key={key} data-testid={`row-${area.id}-${key}`}>
              <span className="lbl">{rowLabel(area.id, key, lang)}</span>
              <b>{x.main}</b>
              {x.detail ? <span className="ci">{x.detail}</span> : null}
              {x.ci ? <span className="ci">{L.ci}: {x.ci}</span> : null}
            </div>
          );
        })}
      </div>
      {note ? <p className="card callout" role="note" data-testid={`note-${area.id}`}><Icon name="scale" size={24} /><span>{note}</span></p> : null}
      <ul className="area-prov">
        <li>{L.artifact}: <code dir="ltr">{area.artifact}</code>{area.date ? <> · {L.date}: <code dir="ltr">{area.date}</code></> : null}</li>
        {area.provenance ? <li>{L.provenance}: <code dir="ltr" lang="en">{area.provenance}</code></li> : null}
        {area.route || area.model ? <li>{L.route}: <code dir="ltr" lang="en">{area.route || "-"}</code>{area.model ? <> · {L.model}: <code dir="ltr" lang="en">{area.model}</code></> : null}</li> : null}
        {area.caveat ? <li>{L.asPublished}: <span dir="ltr" lang="en">{area.caveat}</span></li> : null}
        {area.runs ? area.runs.map((r) => <li key={r.artifact}><code dir="ltr">{r.artifact}</code></li>) : null}
      </ul>
    </section>
  );
}

export default async function ResultsPage() {
  const lang = await serverLang();
  const t = (key: MessageKey, vars?: Record<string, string | number>) => translate(lang, key, vars);
  const local = LOCAL[lang];
  const r = loadResults();
  const areas = loadAreas();
  const L = areaLabels(lang);
  const pend = r ? pendingKeys(r.notEvaluated, areas) : { main: [], extra: [] };
  const caps = await loadCapabilities();
  return (
    <main id="main" className="page" data-testid="results-page">
      <div className="wrap">
        <h1 className="page-title">{t("results.title")}</h1>
        <p className="page-lead">{t("results.lead")}</p>

        <ProofStats lang={lang} variant="results" results={r} />

        {!r ? (
          <div className="card state" role="status" data-testid="results-pending">
            <Icon name="clock" size={32} />
            <h2 className="h3">{local.pending}</h2>
            <p className="muted">{local.pendingBody}</p>
          </div>
        ) : (
          <>
            <section aria-labelledby="all-h">
              <div className="sec-head"><h2 id="all-h">{t("results.all.title")}</h2></div>
              {r.splits.map((s) => <SplitBlock key={s.split} view={s} lang={lang} />)}
            </section>

            {!caps.t1_measured_model ? (
              <p className="card callout" role="note" data-testid="draft-classifier">
                <Icon name="clock" size={24} />
                <span>{local.draft}</span>
              </p>
            ) : null}

            {areas.length > 0 ? (
              <section aria-labelledby="areas-h" data-testid="areas">
                <div className="sec-head"><h2 id="areas-h">{L.measured}</h2></div>
                <p className="muted">{L.measuredLead}</p>
                {areas.map((a) => <AreaBlock key={a.id} area={a} lang={lang} />)}
              </section>
            ) : null}

            <section className="prose" aria-labelledby="scope-h">
              <h2 id="scope-h">{t("results.scope.title")}</h2>
              <p className="card callout" role="note">
                <Icon name="scale" size={24} />
                <span>{t("results.scope.text")}</span>
              </p>
            </section>

            {pend.main.length + pend.extra.length > 0 ? (
              <section className="prose" aria-labelledby="ne-h" data-testid="not-evaluated">
                <h2 id="ne-h">{t("results.ne.title")}</h2>
                <p>{t("results.ne.lead")}</p>
                <ul className="chips">
                  {pend.main.map((k) => <li className="chip" key={k}>{translateMaybe(lang, "ne", k)}</li>)}
                  {pend.extra.map((k) => <li className="chip" key={k}>{pendingLabel(k, lang)}</li>)}
                </ul>
              </section>
            ) : null}

            <section className="prose" aria-labelledby="prov-h">
              <h2 id="prov-h">{t("results.prov.title")}</h2>
              <ul>
                <li>{t("results.prov.artifact")}: <code>{r.artifact}</code></li>
                <li>{t("results.prov.date")}: <code>{r.createdAt}</code></li>
                <li>{t("results.prov.dataset")}: <code>{r.datasetHash.slice(0, 16)}</code></li>
                <li>{local.scopeRaw}: <code>{r.scope}</code></li>
                <li>{local.commit}: <code>{r.gitSha}</code>{r.gitSha.endsWith("-dirty") ? <> {local.dirty}</> : null}</li>
              </ul>
            </section>
          </>
        )}

        <p className="how-more"><Link href="/docs/evals">{t("results.docs")}</Link></p>
      </div>
    </main>
  );
}
