"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { TIERS, type Evidence, type Verdict } from "@/lib/contracts";
import { pick } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { useDt } from "@/lib/use-dt";
import type { CheckState } from "@/lib/verdict-stream";
import { UntrustedText } from "./Chrome";
import { Icon, PolarityMark } from "./Icon";

const HIT_MS = 1800;
const KEY = "fl_tech_open";

function evidenceText(e: Evidence, lang: "ar" | "en", noDisplay: string, failed: string): string {
  const text = pick(lang, e.display);
  if (e.error) return text ? `${text} · ${failed}` : failed;
  return text || noDisplay;
}

/**
 * One collapsed row at the foot of the verdict: evidence ids, hard rules, the risk score, the tier trace and the
 * check metadata, for technical reviewers (web/design/v2 spec 3.2). Closed by default; the choice is kept for the tab.
 * Every string from the verdict is rendered as a text node.
 */
export function TechnicalDetails({ state, verdict: v }: { state: CheckState; verdict: Verdict }) {
  const { t, lang } = usePrefs();
  const d = useDt();
  const [open, setOpen] = useState(false);
  const [hit, setHit] = useState<{ id: string; n: number } | null>(null);
  const rows = useRef(new Map<string, HTMLElement>());

  useEffect(() => {
    try {
      if (sessionStorage.getItem(KEY) === "1") setOpen(true);
    } catch {
      /* storage unavailable: stay closed */
    }
  }, []);
  const remember = (next: boolean) => {
    setOpen(next);
    try {
      sessionStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      /* ignore */
    }
  };

  useEffect(() => {
    if (!hit) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    rows.current.get(hit.id)?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" });
    const timer = setTimeout(() => setHit(null), HIT_MS);
    return () => clearTimeout(timer);
  }, [hit]);

  const cite = (id: string) => {
    setOpen(true);
    setHit((h) => ({ id, n: (h?.n ?? 0) + 1 }));
  };

  const firstSkipped = TIERS.find((tier) => state.tiers[tier] === "skipped");
  const hadRule = v.evidence.some((e) => e.hard_rule);
  const steps = v.trace ?? [];

  return (
    <details className="tech-details" open={open} onToggle={(e) => remember((e.currentTarget as HTMLDetailsElement).open)} data-testid="tech-details">
      <summary data-testid="tech-summary">
        <Icon name="list" size={22} />
        <span>
          <b>{d("tech.toggle")}</b>
          <small>{d("tech.summary")}</small>
        </span>
      </summary>
      <div className="tech-body">
        <div className="risk">
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
        </div>

        {v.reasons.some((r) => r.evidence_ids.length > 0) ? (
          <div className="tech-reasons">
            <h4>{d("tech.reasons")}</h4>
            <ol>
              {v.reasons.map((r, i) => (
                <li key={i}>
                  <span className="small">{d("tech.reason", { n: i + 1 })}</span>
                  <div className="cites">
                    {r.evidence_ids.map((id) => {
                      const cited = v.evidence.find((e) => e.id === id);
                      return (
                        <span key={id} className="cite-wrap">
                          <button className="cite" type="button" aria-label={`${t("cite.go")} ${id}`} data-testid="cite" data-evidence={id} onClick={() => cite(id)}>
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
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <div className="trail tech" data-testid="timeline">
          {TIERS.map((tier) => {
            const status = state.tiers[tier];
            const evidence = v.evidence.filter((e) => e.tier === tier);
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
                    <div
                      key={e.id}
                      ref={(node: HTMLDivElement | null) => {
                        if (node) rows.current.set(e.id, node);
                        else rows.current.delete(e.id);
                      }}
                      className={hit?.id === e.id ? "ev hit" : "ev"}
                      data-polarity={e.polarity}
                      data-evidence={e.id}
                      data-testid="evidence-row"
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
                    </div>
                  ))}
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

        <div className="meta">
          <span>{t("m.id")} <b className="mono" data-testid="verdict-id">{v.verdict_id}</b></span>
          <span>{t("m.tier")} <b className="mono">{v.tier_reached}</b></span>
          <span>{t("m.route")} <b>{t(`m.${v.model_route}`)}</b></span>
          <span>{t("m.time")} <b className="mono">{(v.latency_ms / 1000).toFixed(1)} s</b></span>
          <span>{t("m.source")} <b>{t(`src.${v.source ?? "live"}`)}</b></span>
        </div>

        <p className="tech-docs"><Link href="/docs/cascade">{d("tech.docs")}</Link></p>
      </div>
    </details>
  );
}
