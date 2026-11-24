"use client";

import { useEffect, useState } from "react";
import { parseConfig, type ObsConfig } from "./observability";

const KEY_STORE = "fl_operator_key";
/** One request per page load, shared by every row and card. */
let shared: Promise<ObsConfig | null> | null = null;

/** The observability config, but only for an operator: null (and no request at all) without a key in sessionStorage. */
export function useOperatorObs(): ObsConfig | null {
  const [cfg, setCfg] = useState<ObsConfig | null>(null);
  useEffect(() => {
    let key = "";
    try {
      key = window.sessionStorage.getItem(KEY_STORE) ?? "";
    } catch {
      /* storage blocked: treated as a public visitor */
    }
    if (!key) return;
    let live = true;
    shared ??= fetch("/api/obs-config", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then(parseConfig)
      .catch(() => {
        shared = null; // retry on the next mount
        return null;
      });
    void shared.then((c) => live && setCfg(c));
    return () => {
      live = false;
    };
  }, []);
  return cfg;
}
