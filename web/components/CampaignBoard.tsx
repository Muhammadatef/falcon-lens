"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { loadBoard } from "@/lib/api";
import { parseCampaign, unwrapList, type Campaign } from "@/lib/contracts";
import { formatTime, pick } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { CampaignExplainer } from "./CampaignExplainer";
import { HuntFeed } from "./HuntFeed";
import { DemoRibbon, SourceBadge } from "./Chrome";
import { Icon, SeverityMark, severityPath } from "./Icon";

type Load = { state: "loading" } | { state: "not_connected" } | { state: "ok"; items: Campaign[] };

const MAX_DOTS = 40;
const MAX_CLUSTERS = 6;

/** Small deterministic hash → [0, 1): dots keep their place between renders without Math.random. */
function unit(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return ((h >>> 0) % 10000) / 10000;
}

const polar = (r: number, deg: number): [number, number] => [200 + r * Math.sin((deg * Math.PI) / 180), 200 - r * Math.cos((deg * Math.PI) / 180)];

export function upsertCampaigns(current: Campaign[], incoming: Campaign[]): Campaign[] {
  const byId = new Map(current.map((c) => [c.id, c]));
  for (const c of incoming) byId.set(c.id, c);
  return [...byId.values()];
}

export function CampaignBoard({ demo }: { demo: boolean }) {
  const { t, lang } = usePrefs();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [live, setLive] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const source = useRef<EventSource | null>(null);

  const retry = useCallback(() => {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const abort = new AbortController();

    if (demo) {
      void import("@/lib/demo").then(({ DEMO_CAMPAIGNS }) => {
        if (!cancelled) setLoad({ state: "ok", items: DEMO_CAMPAIGNS.map(parseCampaign).filter((c): c is Campaign => c !== null) });
      });
      return () => { cancelled = true; };
    }

    const closeStream = () => {
      source.current?.close();
      source.current = null;
      setLive(false);
    };

    const onData = (event: Event) => {
      let raw: unknown;
      try {
        raw = JSON.parse((event as MessageEvent).data as string);
      } catch {
        return;
      }
      const list = Array.isArray(raw) || unwrapList(raw).length > 0 ? unwrapList(raw) : [raw];
      const incoming = list.map(parseCampaign).filter((c): c is Campaign => c !== null);
      if (incoming.length === 0) return;
      const replace = Array.isArray(raw) || list.length > 1;
      setLoad((prev) => ({ state: "ok", items: replace || prev.state !== "ok" ? incoming : upsertCampaigns(prev.items, incoming) }));
      if (!replace && incoming[0]) setFresh(incoming[0].id);
    };

    const openStream = () => {
      closeStream();
      const es = new EventSource("/api/public/campaigns/stream");
      source.current = es;
      es.onopen = () => setLive(true);
      es.onerror = () => {
        // Leave reconnection to the browser unless the endpoint is gone for good.
        if (es.readyState === EventSource.CLOSED) closeStream();
        else setLive(false);
      };
      for (const name of ["message", "campaign", "campaigns"]) es.addEventListener(name, onData);
    };

    const refresh = async () => {
      const result = await loadBoard("/api/public/campaigns", parseCampaign, unwrapList, undefined, abort.signal);
      if (cancelled) return;
      if (result.state !== "ok") return setLoad({ state: "not_connected" });
      setLoad({ state: "ok", items: result.items });
      if (!document.hidden) openStream();
    };

    // Updates pause while the tab is hidden (DESIGN.md §7).
    const onVisibility = () => {
      if (document.hidden) closeStream();
      else void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    void refresh();
    return () => {
      cancelled = true;
      abort.abort();
      document.removeEventListener("visibilitychange", onVisibility);
      closeStream();
    };
  }, [demo, attempt]);

  useEffect(() => {
    if (!fresh) return;
    const timer = setTimeout(() => setFresh(null), 4400);
    return () => clearTimeout(timer);
  }, [fresh]);

  const items = useMemo(() => {
    if (load.state !== "ok") return [];
    const rank = { critical: 0, high: 1, medium: 2, low: 3 } as const;
    return [...load.items].sort((a, b) => rank[a.severity] - rank[b.severity] || (b.lastSeen ?? "").localeCompare(a.lastSeen ?? ""));
  }, [load]);

  return (
    <>
      {demo ? <DemoRibbon /> : null}
      <main id="main">
        <section aria-labelledby="board-title">
          <div className="wrap">
            <div className="sec-head">
              <h1 className="page-title" id="board-title">{t("board.title")}</h1>
              {demo ? <SourceBadge source="synthetic" /> : null}
              {!demo && load.state === "ok" ? (
                <span className={live ? "pill pill--live pill--brand" : "pill"} data-testid="live-pill">{t(live ? "board.live" : "board.paused")}</span>
              ) : null}
            </div>
            <p className="sec-sub">{t("board.sub")}</p>
            <CampaignExplainer />

            {load.state === "loading" ? (
              <div className="board-grid board-grid--loading" role="status" aria-busy="true" data-testid="board-loading">
                <div className="card radar">
                  <div className="radar-box radar-skel sk" aria-hidden="true" />
                  <p className="small radar-cap">{t("board.loading")}</p>
                </div>
                <div className="camps" aria-hidden="true">
                  {[0, 1, 2].map((n) => <div key={n} className="card camp camp-skel sk" />)}
                </div>
              </div>
            ) : load.state === "not_connected" ? (
              <div className="card state" role="status" data-testid="board-not-connected">
                <Icon name="unplug" size={40} />
                <h2 className="h3">{t("board.nc.title")}</h2>
                <p className="muted">{t("board.nc.body")}</p>
                <button className="btn" type="button" onClick={retry}><Icon name="refresh" size={20} />{t("retry")}</button>
              </div>
            ) : items.length === 0 ? (
              <div className="card state" role="status" data-testid="board-empty">
                <Icon name="no_warning_signs" size={40} />
                <h2 className="h3">{t("board.empty.title")}</h2>
                <p className="muted">{t("board.empty.body")}</p>
              </div>
            ) : (
              <div className="board-grid">
                <div className="card radar">
                  <Radar items={items} fresh={fresh} focus={focus} label={t("board.title")} />
                  <p className="small radar-cap">{t("radar.cap")}</p>
                </div>
                <div className="camps" data-testid="campaigns">
                  {items.map((c, i) => (
                    <article
                      key={c.id}
                      className={fresh === c.id ? "card camp bump" : "card camp"}
                      data-sev={c.severity}
                      data-testid="campaign-card"
                      onMouseEnter={() => setFocus(c.id)}
                      onMouseLeave={() => setFocus(null)}
                    >
                      <span className="camp-n mono">{i + 1}</span>
                      <div>
                        <span className="sev"><SeverityMark severity={c.severity} />{t("sev")}: {t(`sev.${c.severity}`)}</span>
                        <SourceBadge source={c.source} />
                        <h2 dir="auto">{pick(lang, c.title) || t("camp.untitled")}</h2>
                        <div className="camp-stats">
                          <span><b className="mono">{c.count}</b> {t("linked")}</span>
                          {c.lastSeen ? <span>{t("seen")} <time dateTime={c.lastSeen}>{formatTime(lang, c.lastSeen, true)}</time></span> : null}
                        </div>
                        {c.series.length > 1 ? <Spark series={c.series} /> : null}
                        {pick(lang, c.advice) ? (
                          <p className="camp-advice"><Icon name="hand" size={20} /><span dir="auto">{pick(lang, c.advice)}</span></p>
                        ) : null}
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
        {demo ? null : <HuntFeed />}
      </main>
    </>
  );
}

/** Bars as SVG rects: heights are attributes, so no inline style is needed. */
function Spark({ series }: { series: number[] }) {
  const max = Math.max(1, ...series);
  const w = 100 / series.length;
  return (
    <svg className="spark" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      {series.map((value, i) => {
        const h = Math.max(1.5, (value / max) * 32);
        return <rect key={i} className={i === series.length - 1 ? "spark-bar spark-bar--last" : "spark-bar"} x={(i * w + 0.6).toFixed(2)} y={(32 - h).toFixed(2)} width={Math.max(0.5, w - 1.2).toFixed(2)} height={h.toFixed(2)} rx={0.6} />;
      })}
    </svg>
  );
}

function Radar({ items, fresh, focus, label }: { items: Campaign[]; fresh: string | null; focus: string | null; label: string }) {
  const clusters = items.slice(0, MAX_CLUSTERS);
  const total = clusters.reduce((n, c) => n + Math.max(1, c.count), 0);
  const scale = total > MAX_DOTS ? MAX_DOTS / total : 1;
  return (
    <div className="radar-box">
      <svg viewBox="0 0 400 400" role="img" aria-label={label} focusable="false">
        <circle className="radar-ring" cx={200} cy={200} r={60} />
        <circle className="radar-ring" cx={200} cy={200} r={120} />
        <circle className="radar-ring radar-ring--outer" cx={200} cy={200} r={180} />
        <line className="radar-axis" x1={20} y1={200} x2={380} y2={200} />
        <line className="radar-axis" x1={200} y1={20} x2={200} y2={380} />
        {clusters.map((c, i) => {
          const angle = 48 + i * 137.5;
          const radius = 62 + (i % 3) * 38;
          const dots = Math.max(1, Math.round(Math.max(1, c.count) * scale));
          const [lx, ly] = polar(Math.min(radius + 58, 172), angle);
          return (
            <g key={c.id} data-sev={c.severity} data-dim={focus !== null && focus !== c.id ? "true" : undefined}>
              {Array.from({ length: dots }, (_, j) => {
                const rr = radius + (unit(`${c.id}r${j}`) - 0.5) * 60;
                const aa = angle + (unit(`${c.id}a${j}`) - 0.5) * 44;
                const [x, y] = polar(rr, aa);
                const isNew = fresh === c.id && j === dots - 1;
                return (
                  <g key={j} className={isNew ? "node new" : "node"}>
                    <circle className="node-ping" cx={x.toFixed(1)} cy={y.toFixed(1)} r={7} />
                    <path className="node-shape" d={severityPath(c.severity, x, y, 7)} />
                  </g>
                );
              })}
              <g className="cluster-label">
                <circle cx={lx.toFixed(1)} cy={ly.toFixed(1)} r={13} />
                <text x={lx.toFixed(1)} y={ly.toFixed(1)}>{i + 1}</text>
              </g>
            </g>
          );
        })}
      </svg>
      <div className="radar-clip"><div className="radar-sweep" /></div>
    </div>
  );
}
