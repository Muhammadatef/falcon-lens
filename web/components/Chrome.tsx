"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { DataSource } from "@/lib/contracts";
import { defang, splitDefanged } from "@/lib/defang";
import { translate, type MessageKey } from "@/lib/i18n";
import { usePrefs } from "@/lib/prefs";
import { BrandMark, Icon } from "./Icon";

/** Header order (v2): Check · AI agents · Results · For authorities · Docs · Privacy. */
export const NAV_LINKS = [
  { href: "/", key: "nav.check" },
  { href: "/agents", key: "nav.agents" },
  { href: "/results", key: "nav.results" },
  { href: "/authorities", key: "nav.authorities" },
  { href: "/docs", key: "nav.docs" },
  { href: "/privacy", key: "nav.privacy" },
] as const;

/** Footer only: the live board and the operator board. */
export const FOOT_LINKS = [
  { href: "/campaigns", key: "nav.live" },
  { href: "/ops", key: "nav.ops" },
  { href: "/history", key: "nav.history" },
] as const;

const isCurrent = (pathname: string, href: string): "page" | "true" | undefined =>
  pathname === href ? "page" : href !== "/" && pathname.startsWith(`${href}/`) ? "true" : undefined;

export function Header() {
  const { t, lang, theme, setLang, setTheme } = usePrefs();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close the menu after navigating, and with Escape (focus returns to the button).
  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        menuRef.current?.querySelector<HTMLButtonElement>("button.menu-btn")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="top">
      <a className="skip" href="#main">{t("skip")}</a>
      <div className="wrap top-in" ref={menuRef}>
        <Link className="brand" href="/">
          <BrandMark />
          <span>
            {t("brand")}
            <small>FALCON LENS</small>
          </span>
        </Link>
        <nav className="nav" id="site-nav" data-open={open ? "true" : undefined} aria-label={t("nav.label")}>
          {NAV_LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={isCurrent(pathname, l.href)}>
              {t(l.key)}
            </Link>
          ))}
          <div className="nav-theme">
            <button className="tool" type="button" data-testid="theme-toggle-menu" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
              <span>{t(theme === "dark" ? "theme.light" : "theme.dark")}</span>
            </button>
          </div>
        </nav>
        <div className="top-tools">
          <button className="tool" type="button" data-testid="lang-toggle" lang={lang === "ar" ? "en" : "ar"} onClick={() => setLang(lang === "ar" ? "en" : "ar")}>
            <Icon name="globe" size={20} />
            {t("lang.switch")}
          </button>
          <button className="tool tool--theme" type="button" data-testid="theme-toggle" aria-label={t(theme === "dark" ? "theme.light" : "theme.dark")} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
          </button>
          <button className="tool menu-btn" type="button" data-testid="menu-toggle" aria-expanded={open} aria-controls="site-nav" onClick={() => setOpen((v) => !v)}>
            <Icon name={open ? "x" : "menu"} size={20} />
            <span>{t(open ? "nav.menu.close" : "nav.menu")}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  const { t } = usePrefs();
  const pathname = usePathname();
  return (
    <footer>
      <div className="wrap">
        <nav className="foot-nav" aria-label={t("foot.nav")}>
          {[...NAV_LINKS, ...FOOT_LINKS].map((l) => (
            <Link key={l.href} href={l.href} aria-current={isCurrent(pathname, l.href)}>{t(l.key)}</Link>
          ))}
        </nav>
        <p className="foot-brand">{t("foot.1")}</p>
        <p lang="ar" dir="rtl">{translate("ar", "foot.indep")}</p>
        <p lang="en" dir="ltr">{translate("en", "foot.indep")}</p>
        <p>{t("foot.2")}</p>
      </div>
    </footer>
  );
}

/** Full-width ribbon shown on every page opened with ?demo=1. */
export function DemoRibbon() {
  const { t } = usePrefs();
  return (
    <div className="ribbon" role="note" data-testid="demo-ribbon">
      <b>DEMO DATA</b> · <span>{t("demo.ribbon")}</span>
    </div>
  );
}

/** Dashed badge on anything whose `source` is not "live" (DESIGN.md §2.7). */
export function SourceBadge({ source }: { source: DataSource | undefined }) {
  const { t } = usePrefs();
  if (!source || source === "live") return null;
  return (
    <span className="badge-demo" data-testid="source-badge">
      {t("badge.sample")} · {t(`src.${source}` as MessageKey)}
    </span>
  );
}

/**
 * A URL for display: defanged, monospace, LTR-isolated, host emphasised.
 * It is a <code>, never an <a>, and no href is ever built from it.
 */
export function DefangedUrl({ value }: { value: string }) {
  const { t } = usePrefs();
  const parts = splitDefanged(defang(value));
  return (
    <>
      <code className="url mono" translate="no" dir="ltr" data-testid="defanged-url">
        {parts.scheme}
        <strong>{parts.host}</strong>
        {parts.rest}
      </code>
      <p className="url-note">{t("url.note")}</p>
    </>
  );
}

/** Untrusted free text (message echo, trace summary): plain text node, direction auto-detected and isolated. */
export function UntrustedText({ value, className }: { value: string; className?: string }) {
  return (
    <span className={className} dir="auto" translate="no">
      {value}
    </span>
  );
}

/** Registers the offline-shell service worker and shows the offline line when the network drops. */
export function AppShell() {
  const { t } = usePrefs();
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => undefined);
    }
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  if (!offline) return null;
  return (
    <div className="offline-line" role="status">
      <Icon name="unplug" size={20} />
      <span>{t("offline")}</span>
    </div>
  );
}
