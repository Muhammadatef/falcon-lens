"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { loadOne, type OneLoad } from "@/lib/agent-trace-api";
import { TIERS, parseVerdict, type Evidence, type Tier, type TraceStep, type Verdict } from "@/lib/contracts";
import { hostOnly } from "@/lib/history";
import { hT, type HistoryKey } from "@/lib/i18n-history";
import { formatTime, pick } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { DemoRibbon, SourceBadge, UntrustedText } from "./Chrome";
import { Icon, PolarityMark } from "./Icon";

const POLL_MS = 3000;

type View = { state: "loading" } | { state: "not_found" } | { state: "not_connected" } | { state: "ok"; verdict: Verdict };

const useH = () => {
  const { lang } = usePrefs();
  return (key: HistoryKey, vars?: Record<string, string | number>) => hT(lang, key, vars);
};

/** The trace of one Investigator check: layers, evidence, AI calls, verdict. Built only from GET /v1/verdicts/{id}. */
export function CheckTrace({ verdictId, demo }: { verdictId: string; demo: boolean }) {
  const { t } = usePrefs();
  const h = useH();
  const [view, setView] = useState<View>({ state: "loading" });
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const l = { href: demo ? "/history?demo=1" : "/history" };

  useEffect(() => {
    let cancelled = false;
    const abort = new AbortController();
    const tick = async () => {
      let next: View;
      if (demo) {
        const { DEMO_CHECKS } = await import("@/lib/demo-history");
        const v = DEMO_CHECKS[verdictId];
        next = v ? { state: "ok", verdict: v } : { state: "not_found" };
      } else {
        const r: OneLoad<Verdict> = await loadOne(`/api/public/checks/${verdictId}`, parseVerdict, undefined, abort.signal);
        next = r.state === "ok" ? { state: "ok", verdict: r.value } : r.state === "unauthorized" ? { state: "not_connected" } : { state: r.state };
      }
      if (cancelled) return;
      setView((prev) => (next.state === "not_connected" && prev.state === "ok" ? prev : next));
      if (!demo && next.state === "ok" && !next.verdict.final) timer.current = setTimeout(() => void tick(), POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      abort.abort();
      clearTimeout(timer.current);
    };
  }, [demo, verdictId]);

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <section aria-labelledby="check-title">
          <div className="wrap">
            <p><Link className="back" href={l.href} data-testid="check-back">{h("ck.back")}</Link></p>
            <div className="sec-head">
              <h1 className="page-title" id="check-title">{h("ck.title")}</h1>
              {demo ? <SourceBadge source="synthetic" /> : view.state === "ok" ? <SourceBadge source={view.verdict.source} /> : null}
              {view.state === "ok" && !view.verdict.final ? <span className="pill pill--live pill--brand" data-testid="check-live">{t("board.live")}</span> : null}
            </div>
            <p className="sec-sub">{h("ck.sub")}</p>
            {view.state === "loading" ? (
              <div className="card state" role="status" data-testid="check-loading"><p>{h("ck.loading")}</p><div className="sk" /><div className="sk" /></div>
            ) : view.state === "not_found" ? (
              <div className="card state" role="status" data-testid="check-not-found">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{h("ck.nf.title")}</h2>
                <p className="muted">{h("ck.nf.body")}</p>
              </div>
            ) : view.state === "not_connected" ? (
              <div className="card state" role="status" data-testid="check-not-connected">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{t("ops.nc.title")}</h2>
                <p className="muted">{t("ops.nc.body")}</p>
              </div>
            ) : (
              <Body verdict={view.verdict} />
            )}
          </div>
        </section>
      </main>
    </>
  );
}

function Body({ verdict: v }: { verdict: Verdict }) {
  const { t, lang } = usePrefs();
  const h = useH();
  const host = v.input_type === "url" ? hostOnly(v.canonical_url) : null;
  const route = v.model_route;
  return (
    <>
      <article className="card ck-sum" data-testid="check-summary" data-verdict={v.verdict}>
        <div className="ck-sum-top">
          <span className="vpill" data-testid="check-verdict"><Icon name={v.verdict} size={22} />{t(`v.${v.verdict}`)}</span>
          <span className="pill mono" data-testid="check-risk">{t("risk")}: {v.risk_score} / 100</span>
          {v.degraded ? <span className="pill pill--wait" data-testid="check-degraded">{h("ck.degraded")}</span> : null}
          <span className="pill">{h(`hs.route.${route}` as HistoryKey)}</span>
        </div>
        <dl className="kv-list">
          <div><dt>{h("ck.input")}</dt><dd>{t(`kind.${v.input_type}`)}</dd></div>
          {host ? <div><dt>{t("kind.url")}</dt><dd><code className="mono" dir="ltr" translate="no" data-testid="check-host">{host}</code></dd></div> : null}
          {v.impersonated_brand ? <div><dt>{h("ck.brand")}</dt><dd><UntrustedText value={lang === "ar" ? v.impersonated_brand.name_ar : v.impersonated_brand.name_en} /></dd></div> : null}
          {v.channel ? <div><dt>{h("ck.channel")}</dt><dd data-testid="check-channel" data-channel={v.channel}>{h(`ck.channel.${v.channel}` as HistoryKey)}</dd></div> : null}
          <div><dt>{h("ck.latency")}</dt><dd className="mono">{v.latency_ms} ms</dd></div>
          <div><dt>{t("i.first")}</dt><dd>{formatTime(lang, v.created_at, true)}</dd></div>
          <div><dt>ID</dt><dd className="mono" dir="ltr" translate="no">{v.verdict_id}</dd></div>
        </dl>
        {!v.final ? <p className="small" role="status">{h("ck.partial")}</p> : null}
      </article>

      <h2 className="h3 ck-h">{h("ck.tiers")}</h2>
      <ol className="ck-tiers" data-testid="check-tiers">
        {TIERS.map((tier) => <TierCard key={tier} tier={tier} v={v} />)}
      </ol>

      <h2 className="h3 ck-h">{h("ck.ai")}</h2>
      <AiCalls v={v} />

      <h2 className="h3 ck-h">{h("ck.final")}</h2>
      <article className="card ck-final" data-verdict={v.verdict} data-testid="check-final">
        <p className="vpill"><Icon name={v.verdict} size={22} />{t(`v.${v.verdict}`)}</p>
        <h3>{h("ck.reasons")}</h3>
        {v.reasons.length === 0 ? <p className="muted">{h("ck.reasons.none")}</p> : (
          <ol className="ck-reasons">
            {v.reasons.map((r, i) => (
              <li key={i} data-testid="check-reason">
                <UntrustedText value={pick(lang, r)} />
                <span className="kv">{r.evidence_ids.map((id) => <span key={id}>{id}</span>)}</span>
              </li>
            ))}
          </ol>
        )}
        {v.degraded_reasons && v.degraded_reasons.length > 0 ? (
          <p className="small">{h("ck.codes")}: {v.degraded_reasons.map((c) => <code key={c} className="mono" translate="no"> {c}</code>)}</p>
        ) : null}
      </article>
    </>
  );
}

function TierCard({ tier, v }: { tier: Tier; v: Verdict }) {
  const { lang } = usePrefs();
  const h = useH();
  const reachedIdx = TIERS.indexOf(v.tier_reached);
  const ran = TIERS.indexOf(tier) <= reachedIdx;
  const items = v.evidence.filter((e) => e.tier === tier);
  const reasons = v.degraded_reasons ?? [];
  const why = ran ? null : !v.final ? h("ck.skip.pending") : v.degraded && reasons.length > 0 ? h("ck.skip.degraded", { reasons: reasons.join(", ") }) : h("ck.skip.settled");
  return (
    <li className="card ck-tier" data-testid="check-tier" data-tier={tier} data-state={ran ? "ran" : "skipped"}>
      <div className="ck-tier-top">
        <span className="ck-code mono" translate="no">{tier}</span>
        <h3>{h(`ck.tier.${tier}` as HistoryKey)}</h3>
        <span className={ran ? "pill pill--brand" : "pill ck-skip"} data-testid="check-tier-state">{ran ? (items.length > 0 ? h("ck.ran") : h("ck.ran.empty")) : h("ck.skipped")}</span>
      </div>
      {why ? <p className="small" data-testid="check-tier-why">{why}</p> : null}
      {items.length > 0 ? (
        <>
          <p className="small">{h("ck.evidence.n", { n: items.length })}</p>
          <ul className="ck-ev">
            {items.map((e) => <EvidenceRow key={e.id} e={e} lang={lang} />)}
          </ul>
        </>
      ) : null}
    </li>
  );
}

function EvidenceRow({ e, lang }: { e: Evidence; lang: "ar" | "en" }) {
  const h = useH();
  const text = pick(lang, e.display);
  return (
    <li className="ck-ev-row" data-testid="check-evidence" data-polarity={e.polarity ?? "neutral"}>
      <PolarityMark polarity={e.polarity ?? "neutral"} />
      <span className="ck-ev-text" dir="auto">
        <UntrustedText value={e.error ? (text ? `${text} · ${h("ck.evidence.failed")}` : h("ck.evidence.failed")) : text || h("ck.evidence.nodisplay")} />
      </span>
      <span className="kv">
        <span>{e.signal}</span>
        <span>{h("ck.weight")} {e.weight}</span>
        {e.hard_rule ? <span>{h("ck.rule")} {e.hard_rule}</span> : null}
      </span>
    </li>
  );
}

const KINDS: readonly TraceStep["kind"][] = ["llm", "tool"];

function AiCalls({ v }: { v: Verdict }) {
  const h = useH();
  const { lang } = usePrefs();
  const steps = (v.trace ?? []).filter((s) => KINDS.includes(s.kind));
  const aiEvidence = v.evidence.filter((e) => e.source.startsWith("llm:"));
  if (steps.length === 0 && aiEvidence.length === 0) return <div className="card state" data-testid="check-ai-none"><p>{h("ck.ai.none")}</p></div>;
  return (
    <div className="card ck-ai" data-testid="check-ai">
      <p className="small">{h("ck.ai.model")} / {h("ck.ai.tokens")}: {h("ck.ai.notstored")}</p>
      <ol className="ck-calls">
        {steps.map((s) => (
          <li key={s.step} data-testid="check-ai-call" data-kind={s.kind}>
            <span className="pill">{h(`ck.ai.kind.${s.kind}` as HistoryKey)}</span>
            <span className="mono" translate="no">{s.name ?? "-"}</span>
            {s.kind === "llm" ? <span className="small">{h("ck.ai.route")}: {h(`hs.route.${v.model_route}` as HistoryKey)}</span> : null}
            {typeof s.ms === "number" ? <span className="small">{h("ck.ai.latency")}: <b className="mono">{s.ms} ms</b></span> : null}
            <span className="ck-call-sum" dir="auto"><UntrustedText value={s.summary} /></span>
          </li>
        ))}
      </ol>
      {aiEvidence.length > 0 ? (
        <>
          <p className="small">{h("ck.ai.evidence")}: {aiEvidence.length}</p>
          <ul className="ck-ev">{aiEvidence.map((e) => <EvidenceRow key={e.id} e={e} lang={lang} />)}</ul>
        </>
      ) : null}
    </div>
  );
}
