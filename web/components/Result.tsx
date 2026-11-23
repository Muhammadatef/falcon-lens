"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import type { Verdict } from "@/lib/contracts";
import { clip } from "@/lib/defang";
import { pick } from "@/lib/i18n";
import { onlyPageNotOpened, pageNotOpened } from "@/lib/page-not-opened";
import { useDt } from "@/lib/use-dt";
import { fadeRise, haptics, reduced, stagger, staggerGroup, verdictPlate } from "@/lib/motion";
import { usePrefs } from "@/lib/prefs";
import { lensStateFor, type CheckState } from "@/lib/verdict-stream";
import { AgentActivity } from "./AgentActivity";
import { DefangedUrl, SourceBadge, UntrustedText } from "./Chrome";
import { Icon } from "./Icon";
import { Lens } from "./Lens";
import { TechnicalDetails } from "./TechnicalDetails";

const asVariants = (v: unknown) => v as Variants;

export function Result({ state, onReset, investigatorLive = false, sentinelLive = false }: { state: CheckState; onReset: () => void; investigatorLive?: boolean; sentinelLive?: boolean }) {
  const { t } = usePrefs();
  const sectionRef = useRef<HTMLElement>(null);
  const still = useReducedMotion() ?? false;

  // Bring the result into view when a check starts (the box is above the fold on a phone).
  useEffect(() => {
    if (state.phase === "submitting" || state.phase === "waiting") {
      sectionRef.current?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
    }
  }, [state.phase, still]);

  // Android haptics on the final verdict; never with reduced motion.
  const finalVerdict = state.phase === "final" ? state.verdict : null;
  useEffect(() => {
    if (!finalVerdict || still || state.demo) return;
    const pattern = haptics[finalVerdict.verdict];
    if (pattern.length > 0 && typeof navigator.vibrate === "function") navigator.vibrate([...pattern]);
  }, [finalVerdict, still, state.demo]);

  const v = state.verdict;
  return (
    <section ref={sectionRef} id="check" className="result" aria-labelledby="check-title" data-testid="result" data-phase={state.phase}>
      <div className="wrap">
        <div className="sec-head">
          <h2 id="check-title">{t("check.title")}</h2>
          <SourceBadge source={state.demo ? "fixture" : v?.source} />
          <button className="btn btn--sm sec-action" type="button" onClick={onReset} data-testid="new-check">
            <Icon name="refresh" size={18} />
            {t("btn.again")}
          </button>
        </div>
        <CaseHeader state={state} />
        <div className="check-grid">
          <article className="card verdict" data-verdict={finalVerdict?.verdict} aria-live="polite" aria-busy={state.phase === "waiting" || state.phase === "streaming" || state.phase === "submitting"} data-testid="verdict-card">
            <VerdictBody state={state} still={still} />
          </article>
          {state.phase !== "failed" || v ? (
            <aside className="card trail-card" aria-label={t("check.title")}>
              <AgentActivity state={state} investigatorLive={investigatorLive} sentinelLive={sentinelLive} />
            </aside>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function CaseHeader({ state }: { state: CheckState }) {
  const { t } = usePrefs();
  const v = state.verdict;
  const status =
    state.phase === "final" ? "status.done" : state.phase === "interrupted" ? "status.interrupted" : state.phase === "failed" ? "status.failed" : state.phase === "submitting" ? "status.submitting" : "status.checking";
  const url = v?.canonical_url ?? (state.input?.kind === "url" ? state.input.text : null);
  const kind = v?.input_type ?? state.input?.kind ?? "url";
  return (
    <div className="card case">
      <Lens mini state={lensStateFor(state.phase)} verdict={state.phase === "final" ? v?.verdict : null} tiers={state.tiers} />
      <div className="case-main">
        <div className="case-status" data-testid="case-status">
          <span>{t(status)}</span>
          <AnimatePresence>
            {state.provisional && state.phase === "streaming" ? (
              <m.span key={state.provisional} className="chip-prov" data-verdict={state.provisional} data-testid="provisional-chip" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <Icon name={state.provisional} size={18} />
                {t(`prov.${state.provisional}`)}
              </m.span>
            ) : null}
          </AnimatePresence>
        </div>
        {url ? (
          <DefangedUrl value={url} />
        ) : (
          <p className="case-echo">
            <span className="pill">
              <Icon name={kind} size={16} />
              {t(`kind.${kind}`)}
            </span>
            {state.input && state.input.kind !== "url" ? (
              <>
                <span className="vh">{t("input.echo")}</span>
                <UntrustedText className="case-echo-text" value={clip(state.input.text)} />
              </>
            ) : null}
          </p>
        )}
      </div>
    </div>
  );
}

const SLOW_AFTER_MS = 8000;

/** Appears after a few seconds so a slow check reads as "still working", not as a hang. Announced politely. */
function SlowNote() {
  const { t } = usePrefs();
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_AFTER_MS);
    return () => clearTimeout(timer);
  }, []);
  return (
    <div role="status" aria-live="polite" data-testid="slow-note">
      {slow ? (
        <div className="slow">
          <Icon name="clock" size={24} />
          <div>
            <b>{t("slow.title")}</b>
            <p className="muted">{t("slow.body")}</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function VerdictBody({ state, still }: { state: CheckState; still: boolean }) {
  const { t, lang } = usePrefs();
  const d = useDt();
  const v = state.verdict;

  if (state.phase === "failed" && state.problem) {
    const p = state.problem;
    return (
      <div className="notice notice--problem" role="alert" data-testid="problem" data-problem={p.kind}>
        <h3 className="h3">
          <Icon name={p.kind === "network" ? "unplug" : p.kind === "rate_limited" ? "clock" : "suspicious"} size={28} />
          {t("p.title")}
        </h3>
        <p className="notice-lead">{t(`p.${p.kind}`)}</p>
        {p.kind === "rate_limited" && p.retryAfter ? (
          <p data-testid="retry-after">{p.retryAfter >= 90 ? t("p.retry_in_min", { n: Math.ceil(p.retryAfter / 60) }) : t("p.retry_in", { n: p.retryAfter })} {t("p.retry_hint")}</p>
        ) : null}
        <p className="muted">{t("p.nolink")}</p>
      </div>
    );
  }

  if (state.phase === "interrupted") {
    return (
      <>
        <div className="notice notice--problem" role="alert" data-testid="interrupted">
          <h3 className="h3">
            <Icon name="unplug" size={28} />
            {t("interrupted.title")}
          </h3>
          <p className="notice-lead">{t("interrupted.body")}</p>
        </div>
        {v ? <TechnicalDetails state={state} verdict={v} /> : null}
      </>
    );
  }

  if (!v || !v.final) {
    return (
      <div className="pending" data-testid="pending">
        <p>
          <Icon name="hand" size={24} />
          <span>{t("prov.wait")}</span>
        </p>
        <SlowNote />
        <div className="sk" />
        <div className="sk" />
        <div className="sk" />
      </div>
    );
  }

  const plate = asVariants(still ? reduced.fade : verdictPlate);
  const item = asVariants(still ? reduced.fade : fadeRise);
  const group = asVariants(staggerGroup(still ? 0 : stagger.reasons, still ? 0 : 0.24));
  const brand = v.impersonated_brand ? (lang === "ar" ? v.impersonated_brand.name_ar : v.impersonated_brand.name_en) : "";
  const channels = v.actions.report.channels ?? [];
  const channelSource = channels[0];
  const now = v.actions.now[lang];
  const acted = v.actions.if_already_acted[lang];
  const caution = v.actions.caution?.[lang] ?? [];
  const reportLine = pick(lang, v.actions.report);

  return (
    <>
      <m.div className="plate" variants={plate} initial={state.singleEvent && still ? false : "hidden"} animate="visible" data-testid="verdict-plate">
        <Icon name={v.verdict} size={56} />
        <div>
          <h3 data-testid="verdict-word">{t(`v.${v.verdict}`)}</h3>
          <p>{t(`v.${v.verdict}.sub`)}</p>
        </div>
      </m.div>

      <m.div className="vbody" variants={group} initial="hidden" animate="visible">
        {v.degraded && v.verdict !== "dangerous" && pageNotOpened(v.degraded_reasons) ? (
          <m.div className="degraded" variants={item} role="note" data-testid="page-not-opened">
            <Icon name="unplug" size={24} />
            <div>
              <b>{d("noopen.title")}</b>
              <p>{d("noopen.body")}</p>
            </div>
          </m.div>
        ) : null}
        {v.degraded && !onlyPageNotOpened(v.degraded_reasons) ? (
          <m.div className="degraded" variants={item} role="note" data-testid="degraded">
            <Icon name="unplug" size={24} />
            <div>
              <b>{t("degraded.title")}</b>
              <p>{t("degraded.body")}</p>
            </div>
          </m.div>
        ) : null}

        {brand ? (
          <m.p className="imp" variants={item} data-testid="impersonated">
            <Icon name="eye" size={20} />
            {t("imp")} <b><bdi>{brand}</bdi></b>
          </m.p>
        ) : null}

        {v.reasons.length > 0 ? (
          <m.div variants={item}>
            <h3 className="h3">{t("why")}</h3>
            <ol className="reasons" data-testid="reasons">
              {v.reasons.slice(0, 3).map((r, i) => (
                <li key={i}>
                  <p dir="auto">{pick(lang, r)}</p>
                </li>
              ))}
            </ol>
          </m.div>
        ) : null}

        <m.div className="acts" variants={item}>
          {caution.length > 0 ? (
            <div className="act act--caution" data-testid="caution">
              <h4><Icon name="suspicious" size={24} />{t("act.caution")}</h4>
              <TextList items={caution} />
            </div>
          ) : null}
          {now.length > 0 ? (
            <div className="act act--now" data-testid="act-now">
              <h4><Icon name="hand" size={24} />{t("act.now")}</h4>
              <TextList items={now} />
            </div>
          ) : null}
          {acted.length > 0 ? (
            <div className="act" data-testid="act-acted">
              <h4><Icon name="undo" size={24} />{t("act.acted")}</h4>
              <TextList items={acted} />
            </div>
          ) : null}
          {reportLine || channels.length > 0 ? (
            <div className="act act--report" data-testid="act-report">
              <h4><Icon name="flag" size={24} />{t("act.report")}</h4>
              {reportLine ? <p dir="auto">{reportLine}</p> : null}
              {channels.length > 0 ? (
                <ul className="channels">
                  {channels.map((c, i) => (
                    <li className="channel" key={i}>
                      <span>{lang === "ar" ? c.label_ar || c.label_en : c.label_en || c.label_ar}</span>
                      <b translate="no">{c.value}</b>
                    </li>
                  ))}
                </ul>
              ) : null}
              {channelSource ? (
                <p className="small">
                  {t("ch.source")} <span className="mono">{hostOf(channelSource.source_url)}</span> · {t("ch.verified")} <span className="mono">{channelSource.retrieved_at}</span>
                </p>
              ) : null}
              <p className="small">{t("indep")}</p>
            </div>
          ) : null}
        </m.div>
      </m.div>

      <TechnicalDetails state={state} verdict={v} />
    </>
  );
}

/** Host of a source URL as plain text (the full URL is never rendered as a link). */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

function TextList({ items }: { items: string[] }) {
  return (
    <ul>
      {items.map((x, i) => (
        <li key={i} dir="auto">{x}</li>
      ))}
    </ul>
  );
}

export type { Verdict };
