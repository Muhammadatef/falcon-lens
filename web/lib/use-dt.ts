"use client";

import { dt, type DocKey } from "./i18n-docs";
import { usePrefs } from "./prefs";

/** Translator for the v2 result, docs and authorities strings (lib/i18n-docs.ts). */
export function useDt() {
  const { lang } = usePrefs();
  return (key: DocKey, vars?: Record<string, string | number>) => dt(lang, key, vars);
}
