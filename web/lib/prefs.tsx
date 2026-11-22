"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";
import type { Lang } from "./contracts";
import { dirOf, translate, type MessageKey } from "./i18n";

export type Theme = "dark" | "light";

interface Prefs {
  lang: Lang;
  dir: "rtl" | "ltr";
  theme: Theme;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  setLang: (lang: Lang) => void;
  setTheme: (theme: Theme) => void;
}

const PrefsContext = createContext<Prefs | null>(null);

const YEAR = 60 * 60 * 24 * 365;
const remember = (name: string, value: string) => {
  document.cookie = `${name}=${value}; Path=/; Max-Age=${YEAR}; SameSite=Lax${location.protocol === "https:" ? "; Secure" : ""}`;
};

/** Same-document cross-fade where supported; a plain update otherwise or with reduced motion. */
function withViewTransition(update: () => void) {
  const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!reduced && typeof doc.startViewTransition === "function") doc.startViewTransition(() => flushSync(update));
  else update();
}

export function PrefsProvider({ initialLang, initialTheme, nonce, children }: { initialLang: Lang; initialTheme: Theme; nonce?: string; children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const [theme, setThemeState] = useState<Theme>(initialTheme);

  // <html> is rendered by the server from the same cookies; keep it in step after a toggle.
  useEffect(() => {
    const root = document.documentElement;
    root.lang = lang;
    root.dir = dirOf(lang);
    root.dataset.theme = theme;
  }, [lang, theme]);

  const setLang = useCallback((next: Lang) => {
    remember("fl_lang", next);
    withViewTransition(() => setLangState(next));
  }, []);
  const setTheme = useCallback((next: Theme) => {
    remember("fl_theme", next);
    withViewTransition(() => setThemeState(next));
  }, []);

  const value = useMemo<Prefs>(
    () => ({ lang, dir: dirOf(lang), theme, t: (key, vars) => translate(lang, key, vars), setLang, setTheme }),
    [lang, theme, setLang, setTheme],
  );

  return (
    <PrefsContext.Provider value={value}>
      <MotionConfig reducedMotion="user" nonce={nonce}>
        <LazyMotion features={domAnimation} strict>
          {children}
        </LazyMotion>
      </MotionConfig>
    </PrefsContext.Provider>
  );
}

export function usePrefs(): Prefs {
  const value = useContext(PrefsContext);
  if (!value) throw new Error("usePrefs must be used inside PrefsProvider");
  return value;
}
