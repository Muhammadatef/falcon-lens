"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, useReducedMotion, type Variants } from "motion/react";
import * as m from "motion/react-m";
import { TIERS, type Evidence, type Verdict } from "@/lib/contracts";
import { clip } from "@/lib/defang";
import { pick } from "@/lib/i18n";
import { evidenceRow, fadeRise, haptics, reduced, stagger, staggerGroup, verdictPlate } from "@/lib/motion";
import { usePrefs } from "@/lib/prefs";
import { lensStateFor, type CheckState } from "@/lib/verdict-stream";
import { DefangedUrl, SourceBadge, UntrustedText } from "./Chrome";
import { Icon, PolarityMark } from "./Icon";
import { Lens } from "./Lens";

const HIT_MS = 1800;
const asVariants = (v: unknown) => v as Variants;

export function Result({ state, onReset }: { state: CheckState; onReset: () => void }) {
  const { t } = usePrefs();
  const [hit, setHit] = useState<{ id: string; n: number } | null>(null);
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

  useEffect(() => {
    if (!hit) return;
    const timer = setTimeout(() => setHit(null), HIT_MS);
    return () => clearTimeout(timer);
  }, [hit]);

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
            <VerdictBody state={state} still={still} onCite={(id) => setHit((h) => ({ id, n: (h?.n ?? 0) + 1 }))} />
          </article>
          {state.phase !== "failed" || v ? (
            <aside className="card trail-card">
              <Timeline state={state} hit={hit} still={still} />
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

function VerdictBody({ state, still, onCite }: { state: CheckState; still: boolean; onCite: (id: string) => void }) {
  const { t, lang } = usePrefs();
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
        {p.kind === "rate_limited" && p.retryAfter ? <p data-testid="retry-after">{t("p.retry_in", { n: p.retryAfter })}</p> : null}
        <p className="muted">{t("p.nolink")}</p>
      </div>
    );
  }

  if (state.phase === "interrupted") {
    return (
      <div className="notice notice--problem" role="alert" data-testid="interrupted">
        <h3 className="h3">
          <Icon name="unplug" size={28} />
          {t("interrupted.title")}
        </h3>
        <p className="notice-lead">{t("interrupted.body")}</p>
      </div>
    );
  }

  if (!v || !v.final) {
    return (
      <div className="pending" data-testid="pending">
        <p>
          <Icon name="hand" size={24} />
          <span>{t("prov.wait")}</span>
        </p>
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
        {v.degraded ? (
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

        <m.div className="risk" variants={item}>
          <div className="risk-top">
            <span>{t("risk")}</span>
            <b data-testid="risk-score">{v.risk_score} / 100</b>
          </div>
          <div className="band" role="img" aria-label={`${t("risk")} ${v.risk_score} / 100`}>
            <i />
            <span className="band-fill" style={{ inlineSize: `${v.risk_score}%` }} />
            <span className="band-mark" style={{ insetInlineStart: `${v.risk_score}%` }} />
          </div>
          <p className="small">{t("risk.note")}</p>
        </m.div>

        {v.reasons.length > 0 ? (
          <m.div variants={item}>
            <h3 className="h3">{t("why")}</h3>
            <ol className="reasons" data-testid="reasons">
              {v.reasons.map((r, i) => (
                <li key={i}>
                  <div>
                    <p dir="auto">{pick(lang, r)}</p>
                    {r.evidence_ids.length > 0 ? (
                      <div className="cites">
                        {t("cite")}
                        {r.evidence_ids.map((id) => {
                          const cited = v.evidence.find((e) => e.id === id);
                          return (
                            <span key={id} className="cite-wrap">
                              <button className="cite" type="button" aria-label={`${t("cite.go")} ${id}`} data-testid="cite" data-evidence={id} onClick={() => onCite(id)}>
                                {id}
                              </button>
                              {cited?.hard_rule ? (
                                <span className="tag-rule" data-polarity={cited.polarity}>
                                  {t("rule")} <bdi>{cited.hard_rule}</bdi>
                                </span>
                              ) : null}
                            </span>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
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

      <div className="meta">
        <span>{t("m.id")} <b className="mono" data-testid="verdict-id">{v.verdict_id}</b></span>
        <span>{t("m.tier")} <b className="mono">{v.tier_reached}</b></span>
        <span>{t("m.route")} <b>{t(`m.${v.model_route}`)}</b></span>
        <span>{t("m.time")} <b className="mono">{(v.latency_ms / 1000).toFixed(1)} s</b></span>
        <span>{t("m.source")} <b>{t(`src.${v.source ?? "live"}`)}</b></span>
      </div>
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

function Timeline({ state, hit, still }: { state: CheckState; hit: { id: string; n: number } | null; still: boolean }) {
  const { t, lang, dir } = usePrefs();
  const [tech, setTech] = useState(false);
  const rows = useRef(new Map<string, HTMLElement>());
  const v = state.verdict;
  const fresh = state.singleEvent ? [] : state.freshEvidenceIds;
  const rowVariants = asVariants(still ? { hidden: reduced.fade.hidden, visible: () => reduced.fade.visible } : evidenceRow(dir));
  const firstSkipped = TIERS.find((tier) => state.tiers[tier] === "skipped");
  const hadRule = v?.evidence.some((e) => e.hard_rule) ?? false;

  useEffect(() => {
    if (!hit) return;
    rows.current.get(hit.id)?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" });
  }, [hit, still]);

  const steps = v?.trace ?? [];
  return (
    <div className={tech ? "trail tech" : "trail"} data-testid="timeline">
      <div className="trail-head">
        <h3 className="h3"><Icon name="list" size={22} />{t("trail")}</h3>
        <label className="switch">
          <input type="checkbox" role="switch" checked={tech} onChange={(e) => setTech(e.target.checked)} data-testid="tech-toggle" />
          {t("tech")}
        </label>
      </div>

      {TIERS.map((tier) => {
        const status = state.tiers[tier];
        const evidence = v ? v.evidence.filter((e) => e.tier === tier) : [];
        return (
          <div className="tier" key={tier} data-status={status} data-testid={`tier-${tier}`}>
            <span className="tier-dot" />
            <div className="tier-head">
              <h4>{t(`tier.${tier}`)}</h4>
              <span className="tier-code">{tier}</span>
              <span className="tier-state">{t(`st.${status}`)}</span>
            </div>
            <div className="tier-body">
              {evidence.map((e) => (
                <m.div
                  key={e.id}
                  ref={(node: HTMLDivElement | null) => { if (node) rows.current.set(e.id, node); else rows.current.delete(e.id); }}
                  className={hit?.id === e.id ? "ev hit" : "ev"}
                  data-polarity={e.polarity}
                  data-evidence={e.id}
                  data-testid="evidence-row"
                  variants={rowVariants}
                  custom={Math.max(0, fresh.indexOf(e.id))}
                  initial={fresh.includes(e.id) ? "hidden" : false}
                  animate="visible"
                >
                  <PolarityMark polarity={e.polarity ?? "neutral"} />
                  <div>
                    <p dir="auto">{evidenceText(e, lang, t("ev.nodisplay"), t("ev.failed"))}</p>
                    <div className="ev-meta">
                      <span>{e.id}</span>
                      {e.hard_rule ? <span className="tag-rule" data-polarity={e.polarity}>{e.hard_rule}</span> : null}
                      <span className="ev-tech">{e.signal}</span>
                      <span className="ev-tech">{(e.weight > 0 ? "+" : "") + e.weight.toFixed(1)}</span>
                      <span className="ev-tech">{e.source}</span>
                    </div>
                  </div>
                </m.div>
              ))}
              {status === "running" ? <div className="sk" /> : null}
              {status === "skipped" && tier === firstSkipped ? <p className="tier-note">{t(hadRule ? "skip.rule" : "skip.clear")}</p> : null}
            </div>
          </div>
        );
      })}

      {steps.length > 0 ? (
        <div className="steps" data-testid="trace">
          <h4>{t("steps")}</h4>
          <ol>
            {steps.map((s) => (
              <li key={s.step} data-kind={s.kind}>
                <div className="step-top">
                  <span className="step-kind">{t(`trace.${s.kind}`)}</span>
                  {s.name ? <bdi className="mono step-name">{s.name}</bdi> : null}
                  {typeof s.ms === "number" ? <span className="mono step-ms">{s.ms} ms</span> : null}
                </div>
                <p><UntrustedText value={s.summary} /></p>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function evidenceText(e: Evidence, lang: "ar" | "en", noDisplay: string, failed: string): string {
  const text = pick(lang, e.display);
  if (e.error) return text ? `${text} · ${failed}` : failed;
  return text || noDisplay;
}

export type { Verdict };
