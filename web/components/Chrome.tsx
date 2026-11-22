"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import type { DataSource } from "@/lib/contracts";
import { defang, splitDefanged } from "@/lib/defang";
import { usePrefs } from "@/lib/prefs";
import { BrandMark, Icon } from "./Icon";

export function Header() {
  const { t, lang, theme, setLang, setTheme } = usePrefs();
  const pathname = usePathname();
  const links = [
    { href: "/", label: t("nav.check") },
    { href: "/campaigns", label: t("nav.board") },
    { href: "/ops", label: t("nav.ops") },
  ];
  return (
    <header className="top">
      <a className="skip" href="#main">{t("skip")}</a>
      <div className="wrap top-in">
        <Link className="brand" href="/" aria-label="Falcon Lens | عدسة الصقر">
          <BrandMark />
          <span>
            {t("brand")}
            <small>FALCON LENS</small>
          </span>
        </Link>
        <nav className="nav" aria-label={t("nav.label")}>
          {links.map((l) => (
            <Link key={l.href} href={l.href} aria-current={pathname === l.href ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
        </nav>
        <div className="top-tools">
          <button className="tool" type="button" data-testid="lang-toggle" lang={lang === "ar" ? "en" : "ar"} onClick={() => setLang(lang === "ar" ? "en" : "ar")}>
            <Icon name="globe" size={20} />
            {t("lang.switch")}
          </button>
          <button className="tool" type="button" data-testid="theme-toggle" aria-label={t(theme === "dark" ? "theme.light" : "theme.dark")} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={20} />
          </button>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  const { t } = usePrefs();
  return (
    <footer>
      <div className="wrap">
        <p>{t("foot.1")}</p>
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
  if (!source || source === "live") return null;
  return (
    <span className="badge-demo" data-testid="source-badge">
      DEMO DATA · {source}
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
