"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { loadBoard } from "@/lib/api";
import { parseCampaign, unwrapList, type Campaign } from "@/lib/contracts";
import { pick } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { CapBadge } from "./CapBadge";

type Feed = { kind: "loading" } | { kind: "offline" } | { kind: "ok"; items: Campaign[] };

const POLL_MS = 30_000;
const ANNOUNCE_MS = 10_000;

/** Counts are computed from the response, never typed: campaigns listed, and the checks linked to them. */
export function summarise(items: Campaign[]): { campaigns: number; checks: number; latest: Campaign | null; live: boolean } {
  const latest = [...items].sort((a, b) => Date.parse(b.lastSeen ?? "") - Date.parse(a.lastSeen ?? "") || 0)[0] ?? null;
  return { campaigns: items.length, checks: items.reduce((n, c) => n + c.count, 0), latest, live: items.every((c) => c.source === "live") };
}

/**
 * The Sentinel at work, on Home. Reads GET /v1/campaigns (same endpoint as the live board), refreshes
 * every 30 s while the tab is visible, and never shows a number the API did not return.
 * States: live data, non-live source (dashed DEMO DATA badge), empty, unreachable.
 */
export function SentinelTicker({ demo, sentinelLive }: { demo: boolean; sentinelLive: boolean }) {
  const { t, lang } = usePrefs();
  const [feed, setFeed] = useState<Feed>({ kind: "loading" });
  const [announce, setAnnounce] = useState("");
  const lastAnnounce = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();

    const apply = (next: Feed) => {
      if (cancelled) return;
      setFeed(next);
    };
    const refresh = async () => {
      if (demo) {
        const { DEMO_CAMPAIGNS } = await import("@/lib/demo");
        apply({ kind: "ok", items: DEMO_CAMPAIGNS.map(parseCampaign).filter((c): c is Campaign => c !== null) });
        return;
      }
      const result = await loadBoard("/v1/campaigns", parseCampaign, unwrapList, undefined, abort.signal);
      apply(result.state === "ok" ? { kind: "ok", items: result.items } : { kind: "offline" });
    };
    const loop = async () => {
      if (!document.hidden) await refresh();
      if (!cancelled) timer = setTimeout(() => void loop(), POLL_MS);
    };
    const onVisible = () => {
      if (!document.hidden) {
        clearTimeout(timer);
        void loop();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    void loop();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      abort.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [demo]);

  const s = feed.kind === "ok" ? summarise(feed.items) : null;
  const countText = s ? t("ticker.count", { campaigns: s.campaigns, checks: s.checks }) : "";
  const latestTitle = s?.latest ? pick(lang, s.latest.title) : "";

  // At most one polite announcement per 10 s.
  useEffect(() => {
    if (feed.kind === "loading") return;
    const text = feed.kind === "offline" ? t("ticker.offline") : s && s.campaigns === 0 ? t("ticker.empty") : `${countText}`;
    if (Date.now() - lastAnnounce.current < ANNOUNCE_MS && lastAnnounce.current !== 0) return;
    lastAnnounce.current = Date.now();
    setAnnounce(text);
  }, [feed, s, countText, t]);

  return (
    <section className="ticker" aria-label={t("ticker.aria")} data-testid="sentinel-ticker" data-state={feed.kind === "ok" ? (s && s.campaigns > 0 ? "ok" : "empty") : feed.kind}>
      <div className="wrap ticker-in">
        <span className="ticker-label">
          <i className="ticker-dot" aria-hidden="true" />
          <b>{t("ticker.label")}</b>
          {!sentinelLive ? <CapBadge live={false} lang={lang} /> : null}
          {s && !s.live && s.campaigns > 0 ? <span className="badge-demo" data-testid="ticker-demo">{t("demo.badge")}</span> : null}
        </span>
        <div className="ticker-text">
          {feed.kind === "loading" ? <span className="muted">…</span> : null}
          {feed.kind === "offline" ? <span className="muted" data-testid="ticker-offline">{t("ticker.offline")}</span> : null}
          {s && s.campaigns === 0 ? <span className="muted" data-testid="ticker-empty">{t("ticker.empty")}</span> : null}
          {s && s.campaigns > 0 ? (
            <>
              <span data-testid="ticker-count">{countText}</span>
              {latestTitle ? (
                <span className="ticker-latest">
                  {t("ticker.latest")} <bdi data-testid="ticker-latest" dir="auto">{latestTitle}</bdi>
                </span>
              ) : null}
            </>
          ) : null}
        </div>
        <Link className="ticker-cta" href="/campaigns">{t("ticker.cta")}</Link>
        <p className="vh" aria-live="polite" role="status">{announce}</p>
      </div>
    </section>
  );
}
