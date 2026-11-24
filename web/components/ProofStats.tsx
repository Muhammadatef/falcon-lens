import Link from "next/link";
import type { Lang } from "@/lib/contracts";
import { formatRate, loadLiveFp, type LiveFp } from "@/lib/fp-regress";
import { translate, type MessageKey } from "@/lib/i18n";
import { formatCi, formatMetric, headline, loadResults, type Headline, type ResultsView } from "@/lib/results";
import { Icon } from "./Icon";

/**
 * "Measured, not claimed": the three offline-test numbers, ALWAYS with their scope line, and ALWAYS beside them
 * the live held-out false-alarm measurement. Used by Home (variant "home") and Results (variant "results").
 * Pure: it only formats the bundled artifacts (lib/results.ts, lib/fp-regress.ts); no number is typed here.
 * No count-up animation: these are evidence, not decoration.
 */
export function ProofStats({ lang, variant, results = loadResults(), live = loadLiveFp() }: { lang: Lang; variant: "home" | "results"; results?: ResultsView | null; live?: LiveFp | null }) {
  const t = (key: MessageKey, vars?: Record<string, string | number>) => translate(lang, key, vars);
  const h = headline(results);
  return (
    <div className="proof" data-testid={`proof-${variant}`}>
      {variant === "home" ? (
        <>
          <div className="sec-head">
            <h2 id="proof-home-h">{t("proof.title")}</h2>
          </div>
          <p className="sec-sub">{t("proof.lead")}</p>
        </>
      ) : null}

      {h ? <Offline h={h} lang={lang} variant={variant} t={t} /> : <p className="card callout" role="status" data-testid="proof-pending"><Icon name="clock" size={24} /><span>{t("proof.pending")}</span></p>}

      <LiveFalseAlarm live={live} lang={lang} variant={variant} t={t} />

      {variant === "home" ? (
        <p className="how-more">
          <Link href="/results">{t("proof.cta")}</Link>
        </p>
      ) : null}
    </div>
  );
}

type T = (key: MessageKey, vars?: Record<string, string | number>) => string;

function Offline({ h, lang, variant, t }: { h: Headline; lang: Lang; variant: "home" | "results"; t: T }) {
  const cards = [
    { id: "recall", label: t("proof.recall"), value: formatMetric("recall", h.recall.value, lang), ci: formatCi(h.recall, lang), mean: t("results.recall.mean") },
    { id: "fpr", label: t("proof.fpr"), value: formatMetric("fpr", h.fpr.value, lang), ci: formatCi(h.fpr, lang), mean: t("results.fpr.mean") },
    { id: "official", label: t("proof.official"), value: h.official.toLocaleString(lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB"), ci: "", mean: t("results.official.mean") },
  ];
  return (
    <>
      <p className="proof-kicker">{t("proof.offline.title")}</p>
      <ul className="stats" data-testid="proof-stats">
        {cards.map((c) => (
          <li className="card stat" key={c.id} data-testid={`proof-${c.id}`}>
            <b className="stat-n mono" dir="ltr">{c.value}</b>
            <span className="stat-label">{c.label}</span>
            {c.ci ? <span className="stat-ci">{t("proof.ci")}: <bdi className="mono" dir="ltr">{c.ci}</bdi></span> : null}
            {variant === "results" ? <span className="stat-mean">{c.mean}</span> : null}
          </li>
        ))}
      </ul>
      <p className="scope" data-testid="proof-scope">
        <Icon name="scale" size={22} />
        <span>
          {t("proof.scope", { "test.n": h.n.toLocaleString(lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB") })} <code>{h.artifact}</code>
        </span>
      </p>
    </>
  );
}

function LiveFalseAlarm({ live, lang, variant, t }: { live: LiveFp | null; lang: Lang; variant: "home" | "results"; t: T }) {
  if (!live) return <p className="card callout" role="status" data-testid="live-fp-pending"><Icon name="clock" size={24} /><span>{t("proof.live.pending")}</span></p>;
  const fmt = (row: LiveFp["web"]) => ({ n: row.n.toLocaleString(lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB"), rate: formatRate(row.rate, lang), lo: formatRate(row.lo, lang), hi: formatRate(row.hi, lang) });
  const date = new Date(live.createdAt);
  const day = Number.isNaN(date.getTime()) ? live.createdAt : new Intl.DateTimeFormat(lang === "ar" ? "ar-AE-u-nu-latn" : "en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(date);
  const web = fmt(live.web);
  const Heading = variant === "results" ? "h2" : "h3";
  return (
    <div className="card live-fp" data-testid="live-fp">
      {/* Results has no section heading above this card, so the card title is the h2 there (no skipped level). */}
      <Heading className="h3">
        <Icon name="eye" size={24} />
        {t("proof.live.title")}
      </Heading>
      <p className="live-fp-rate">
        <b className="stat-n mono" dir="ltr" data-testid="live-fp-web-rate">{web.rate}</b>
      </p>
      <p className="live-fp-line" data-testid="live-fp-web">{t("proof.live.web", web)}</p>
      <p className="live-fp-line" data-testid="live-fp-all">{t("proof.live.all", fmt(live.all))}</p>
      <p className="small">
        {t("proof.live.src", { date: day })} <code>{live.artifact}</code>
      </p>
    </div>
  );
}
