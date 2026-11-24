"use client";

import { useEffect, useState } from "react";
import { parseConfig, TRACE_ID_RE, type ObsConfig, type TimeWindow } from "./observability";

const KEY_STORE = "fl_operator_key";
/** One request per page load, shared by every row and card. */
let shared: Promise<ObsConfig | null> | null = null;

/** The operator key from sessionStorage, or "" (public visitor). */
export function operatorKey(): string {
  try {
    return window.sessionStorage.getItem(KEY_STORE) ?? "";
  } catch {
    return "";
  }
}

/** The observability config, but only for an operator: null (and no request at all) without a key in sessionStorage. The server re-checks the key against the API. */
export function useOperatorObs(): ObsConfig | null {
  const [cfg, setCfg] = useState<ObsConfig | null>(null);
  useEffect(() => {
    const key = operatorKey();
    if (!key) return;
    let live = true;
    shared ??= fetch("/api/obs-config", { cache: "no-store", headers: { "x-ops-key": key } })
      .then((r) => (r.ok ? r.json() : null))
      .then(parseConfig)
      .catch(() => null)
      .then((c) => {
        if (c === null) shared = null; // retry on the next mount (wrong key, API down)
        return c;
      });
    void shared.then((c) => live && setCfg(c));
    return () => {
      live = false;
    };
  }, []);
  return cfg;
}

/* Verdict trace ids: requested from the operator route in one batched call per tick, cached for the page's life. */
const traceCache = new Map<string, string | null>();
const pending = new Map<string, ((v: string | null) => void)[]>();
let scheduled = false;

async function flush(): Promise<void> {
  scheduled = false;
  const batch = [...pending.entries()];
  pending.clear();
  const key = operatorKey();
  for (let i = 0; i < batch.length; i += 100) {
    const part = batch.slice(i, i + 100);
    let found: Record<string, unknown> = {};
    try {
      const r = await fetch(`/api/ops/trace-ids?verdicts=${part.map(([id]) => id).join(",")}`, { cache: "no-store", headers: { "x-ops-key": key } });
      if (r.ok) found = ((await r.json()) as { trace_ids?: Record<string, unknown> }).trace_ids ?? {};
    } catch {
      /* no links for this batch */
    }
    for (const [id, waiters] of part) {
      const v = typeof found[id] === "string" && TRACE_ID_RE.test(found[id] as string) ? (found[id] as string) : null;
      traceCache.set(id, v);
      waiters.forEach((w) => w(v));
    }
  }
}

/** Trace id of one verdict for an operator (null for the public, while loading, or when there is none). */
export function useVerdictTraceId(verdictId: string): string | null {
  const [tid, setTid] = useState<string | null>(null);
  useEffect(() => {
    if (!operatorKey()) return;
    let live = true;
    if (traceCache.has(verdictId)) {
      setTid(traceCache.get(verdictId) ?? null);
      return;
    }
    pending.set(verdictId, [...(pending.get(verdictId) ?? []), (v) => live && setTid(v)]);
    if (!scheduled) {
      scheduled = true;
      queueMicrotask(() => void setTimeout(() => void flush(), 30));
    }
    return () => {
      live = false;
    };
  }, [verdictId]);
  return tid;
}

export interface IncidentTraceInfo {
  traceId?: string;
  window: TimeWindow | null;
}

/** Latest run trace id and run time span of one incident, for an operator. */
export function useIncidentTrace(incidentId: string): IncidentTraceInfo | null {
  const [info, setInfo] = useState<IncidentTraceInfo | null>(null);
  useEffect(() => {
    const key = operatorKey();
    if (!key) return;
    const abort = new AbortController();
    fetch(`/api/ops/incident-traces?incidents=${incidentId}`, { cache: "no-store", headers: { "x-ops-key": key }, signal: abort.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((raw: { traces?: Record<string, { trace_id?: unknown; from?: unknown; to?: unknown }> } | null) => {
        const t = raw?.traces?.[incidentId];
        const tid = typeof t?.trace_id === "string" && TRACE_ID_RE.test(t.trace_id) ? t.trace_id : undefined;
        const win = typeof t?.from === "number" && typeof t?.to === "number" ? { from: t.from - 60_000, to: t.to + 120_000 } : null;
        setInfo({ ...(tid ? { traceId: tid } : {}), window: win });
      })
      .catch(() => undefined);
    return () => abort.abort();
  }, [incidentId]);
  return info;
}
