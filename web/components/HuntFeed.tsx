"use client";

import { useCallback, useEffect, useState } from "react";
import { parsePublicHunt, unconfirmedCount, type HuntItem, type PublicHunt } from "@/lib/hunt";
import { formatTime, pick, type MessageKey } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { SourceBadge } from "./Chrome";
import { Icon } from "./Icon";

type Load = { state: "loading" } | { state: "not_connected" } | { state: "ok"; data: PublicHunt };
type T = ReturnType<typeof usePrefs>["t"];

/** Human duration from seconds the API measured (never a typed figure). */
export function huntDuration(t: T, s: number): string {
  if (s < 3600) return t("hunt.min", { n: Math.max(1, Math.round(s / 60)) });
  if (s < 86400) return t("hunt.hours", { n: Math.round(s / 3600) });
  return t("hunt.days", { n: Math.round(s / 86400) });
}

/** "Hunting | الرصد الاستباقي" on /campaigns (docs/design/HUNTER.md section 6).
 *  Only arbiter-confirmed candidates are listed; domains are plain defanged text, never a link; every figure
 *  comes from the API response. */
export function HuntFeed() {
  const { t } = usePrefs();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    void (async () => {
      try {
        const res = await fetch("/api/public/hunt", { cache: "no-store", signal: abort.signal });
        const data = res.ok ? parsePublicHunt(await res.json()) : null;
        if (!abort.signal.aborted) setLoad(data ? { state: "ok", data } : { state: "not_connected" });
      } catch {
        if (!abort.signal.aborted) setLoad({ state: "not_connected" });
      }
    })();
    return () => abort.abort();
  }, [attempt]);

  return (
    <section aria-labelledby="hunt-title" data-testid="hunt-feed">
      <div className="wrap">
        <div className="sec-head">
          <h2 className="page-title" id="hunt-title">{t("hunt.title")}</h2>
        </div>
        <p className="sec-sub">{t("hunt.sub")}</p>
        {load.state === "loading" ? (
          <div className="card state" role="status" aria-busy="true" data-testid="hunt-loading">
            <p className="muted">{t("hunt.loading")}</p>
          </div>
        ) : load.state === "not_connected" ? (
          <div className="card state" role="status" data-testid="hunt-not-connected">
            <Icon name="unplug" size={40} />
            <h3 className="h3">{t("hunt.nc.title")}</h3>
            <p className="muted">{t("hunt.nc.body")}</p>
            <button className="btn" type="button" onClick={retry}><Icon name="refresh" size={20} />{t("retry")}</button>
          </div>
        ) : (
          <HuntBody data={load.data} />
        )}
      </div>
    </section>
  );
}

function HuntBody({ data }: { data: PublicHunt }) {
  const { t } = usePrefs();
  const others = unconfirmedCount(data.counts);
  return (
    <>
      {data.sources.length > 0 ? (
        <div className="hunt-sources camp-stats" data-testid="hunt-sources">
          <span className="small muted">{t("hunt.sources")}:</span>
          {data.sources.map((s) => (
            <span key={s.id} className={s.status === "live" ? "pill pill--live" : "pill"} data-testid={`hunt-source-${s.id}`} data-status={s.status}>
              {t(`hunt.src.${s.id}` as MessageKey)} · {t(`hunt.status.${s.status}` as MessageKey)}
            </span>
          ))}
        </div>
      ) : null}
      {data.enabled === false ? <p className="small" data-testid="hunt-off">{t("hunt.off")}</p> : null}
      {data.paused ? <p className="small" data-testid="hunt-paused">{t("hunt.paused")}</p> : null}
      {data.items.length === 0 ? (
        <div className="card state" role="status" data-testid="hunt-empty">
          <Icon name="eye" size={40} />
          <h3 className="h3">{t("hunt.empty.title")}</h3>
          <p className="muted">{t("hunt.empty.body")}</p>
        </div>
      ) : (
        <ul className="camps hunt-list" data-testid="hunt-items">
          {data.items.map((it) => <HuntRow key={it.id} item={it} />)}
        </ul>
      )}
      {others > 0 ? <p className="small muted" data-testid="hunt-unconfirmed">{t("hunt.unconfirmed", { n: others })}</p> : null}
    </>
  );
}

function HuntRow({ item }: { item: HuntItem }) {
  const { t, lang } = usePrefs();
  const sep = lang === "ar" ? "، " : ", ";
  return (
    <li className="card camp" data-sev={item.verdict === "dangerous" ? "high" : "medium"} data-testid="hunt-item">
      <div>
        <span className="small muted">{t("hunt.suspected")}</span> <SourceBadge source={item.source} />
        <p>
          <code className="url mono" translate="no" dir="ltr" data-testid="hunt-domain">{item.domain}</code>
        </p>
        <p className="small">
          {t("hunt.brand")}: <bdi data-testid="hunt-brand">{item.brandName ? pick(lang, item.brandName) : item.brandId}</bdi>
        </p>
        <div className="camp-stats">
          <span className="pill pill--brand" data-testid="hunt-confirmed">{t("hunt.confirmed")} · {t(`hunt.verdict.${item.verdict}`)}</span>
          {item.foundBeforeReport ? (
            <>
              <span className="pill pill--live" data-testid="hunt-before">{t("hunt.before")}</span>
              <span className="small muted" data-testid="hunt-noreport">{t("hunt.noreport")}</span>
            </>
          ) : null}
        </div>
        <p className="small">
          {t("hunt.first")}: <time dateTime={item.firstSeen}>{formatTime(lang, item.firstSeen, true)}</time>
          {item.ttdSeconds !== null && item.ttdBasis ? (
            <span data-testid="hunt-ttd">
              {" · "}{t("hunt.ttd")}: <b className="mono">{huntDuration(t, item.ttdSeconds)}</b> {t(`hunt.ttd.${item.ttdBasis}`)}
            </span>
          ) : null}
        </p>
        {item.reasons.length > 0 ? (
          <p className="small" data-testid="hunt-reasons">
            {t("hunt.why")}: {item.reasons.map((r) => t(`hunt.reason.${r}` as MessageKey)).join(sep)}
          </p>
        ) : null}
      </div>
    </li>
  );
}
