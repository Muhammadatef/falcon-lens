import { CapBadge } from "@/components/CapBadge";
import type { Lang } from "@/lib/contracts";
import { bundledDspyRows, excludesZero } from "@/lib/dspy-results";
import { at, type ArchKey } from "@/lib/i18n-arch";

const fmt = (v: number) => v.toLocaleString("en-US", { maximumFractionDigits: 4 });

/** "Why DSPy and LangGraph" (docs/TECHNICAL.md has the same text). Server component; the badge comes from the capability flag. */
export function WhyDspyLanggraph({ lang, dspyLive }: { lang: Lang; dspyLive: boolean }) {
  const t = (k: ArchKey) => at(lang, k);
  const rows = dspyLive ? bundledDspyRows() : [];
  return (
    <section className="why prose" aria-labelledby="why-h" data-testid="why-dspy-langgraph">
      <div className="sec-head"><h2 id="why-h">{t("why.title")}</h2></div>
      <p>{t("why.lead")}</p>

      <h3>{t("why.dspy.title")} <CapBadge live={dspyLive} lang={lang} /></h3>
      <p>{t("why.dspy.p1")}</p>
      <p>{t("why.dspy.p2")}</p>
      <p>{t("why.dspy.p3")}</p>
      <p className="card pattern" data-testid="dspy-status">{t(dspyLive ? "why.dspy.live" : "why.dspy.inprogress")}</p>
      {rows.length > 0 ? (
        <div className="tbl-wrap" data-testid="dspy-table">
          <table className="tbl">
            <caption>{t("why.dspy.table")}</caption>
            <thead>
              <tr>
                <th scope="col">role</th>
                <th scope="col">before</th>
                <th scope="col">after</th>
                <th scope="col">paired 95% interval</th>
                <th scope="col">excludes 0</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.artifact}>
                  <th scope="row" className="mono">{r.role}</th>
                  <td className="mono">{fmt(r.before)}</td>
                  <td className="mono">{fmt(r.after)}</td>
                  <td className="mono">{r.low !== null && r.high !== null ? `[${fmt(r.low)}, ${fmt(r.high)}]` : "-"}</td>
                  <td>{excludesZero(r) ? (lang === "ar" ? "نعم" : "yes") : lang === "ar" ? "لا" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small faint">{rows.some((r) => r.synthetic) ? (lang === "ar" ? "بيانات اصطناعية؛ المصدر: الملفات المنشورة في evals/results/published/dspy." : "Synthetic data; source: the published files in evals/results/published/dspy.") : "evals/results/published/dspy"}</p>
        </div>
      ) : null}

      <h3>{t("why.trace.title")}</h3>
      <p>{t("why.trace.p1")}</p>

      <h3>{t("why.lg.title")}</h3>
      <p>{t("why.lg.p1")}</p>
      <ul>
        <li>{t("why.lg.li1")}</li>
        <li>{t("why.lg.li2")}</li>
        <li>{t("why.lg.li3")}</li>
        <li>{t("why.lg.li4")}</li>
      </ul>

      <h3>{t("why.inv.title")}</h3>
      <p>{t("why.inv.p1")}</p>
      <p>{t("why.inv.p2")}</p>
    </section>
  );
}
