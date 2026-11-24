"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { authHeaders } from "./api";
import { unwrapList } from "./contracts";
import { readSse } from "./sse";

export type ListLoad<T> = { state: "loading" } | { state: "not_connected" } | { state: "unauthorized" } | { state: "ok"; items: T[]; next: string | null };

interface Options<T> {
  /** Nothing is fetched until true (the operator key has been read from sessionStorage). */
  enabled: boolean;
  /** Operator key; empty when none is stored. */
  keyValue: string;
  /** Bumped to force a reload (retry button, new key). */
  attempt: number;
  listPath: string;
  streamPath: string;
  /** SSE `event:` name to accept. */
  event: string;
  parse: (raw: unknown) => T | null;
  idOf: (item: T) => string;
  /** Sort order of the merged list (newest first). */
  compare: (a: T, b: T) => number;
  pageSize?: number;
  maxItems?: number;
}

const RECONNECT_MS = 1500;

/**
 * A paginated operator list that is kept current by an authenticated SSE stream (fetch based: EventSource cannot
 * send an Authorization header). The stream reconnects with Last-Event-ID when the server's time box ends it.
 * A failed list call is "not connected" or "unauthorized", never placeholder data.
 */
export function useLiveList<T>(o: Options<T>) {
  const { enabled, keyValue, attempt, listPath, streamPath, event, parse, idOf, compare, pageSize = 50, maxItems = 300 } = o;
  const [load, setLoad] = useState<ListLoad<T>>({ state: "loading" });
  const [live, setLive] = useState(false);
  const [moreBusy, setMoreBusy] = useState(false);
  const parseRef = useRef(parse);
  const idRef = useRef(idOf);
  const cmpRef = useRef(compare);
  parseRef.current = parse;
  idRef.current = idOf;
  cmpRef.current = compare;

  const merge = useCallback(
    (current: T[], incoming: T[]): T[] => {
      const ids = new Set(incoming.map((i) => idRef.current(i)));
      return [...incoming, ...current.filter((c) => !ids.has(idRef.current(c)))].sort(cmpRef.current).slice(0, maxItems);
    },
    [maxItems],
  );

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const abort = new AbortController();
    setLoad({ state: "loading" });
    setLive(false);

    const stream = async () => {
      let lastId = "";
      while (!cancelled) {
        try {
          const headers: Record<string, string> = { ...authHeaders(keyValue || undefined), accept: "text/event-stream" };
          if (lastId) headers["last-event-id"] = lastId;
          const response = await fetch(streamPath, { headers, credentials: "same-origin", cache: "no-store", signal: abort.signal });
          if (!response.ok || !(response.headers.get("content-type") ?? "").includes("text/event-stream")) {
            if (response.status === 401 || response.status === 403) return;
          } else {
            setLive(true);
            await readSse(
              response,
              (message) => {
                if (message.id) lastId = message.id;
                if (message.event !== event) return;
                let raw: unknown;
                try {
                  raw = JSON.parse(message.data);
                } catch {
                  return;
                }
                const item = parseRef.current(raw);
                if (item) setLoad((prev) => (prev.state === "ok" ? { ...prev, items: merge(prev.items, [item]) } : { state: "ok", items: [item], next: null }));
              },
              abort.signal,
            );
          }
        } catch {
          /* aborted or dropped: fall through to the reconnect wait */
        }
        if (cancelled) return;
        setLive(false);
        await new Promise((resolve) => setTimeout(resolve, RECONNECT_MS));
      }
    };

    void (async () => {
      let response: Response;
      try {
        response = await fetch(`${listPath}?limit=${pageSize}`, { headers: authHeaders(keyValue || undefined), credentials: "same-origin", cache: "no-store", signal: abort.signal });
      } catch {
        if (!cancelled) setLoad({ state: "not_connected" });
        return;
      }
      if (cancelled) return;
      if (response.status === 401 || response.status === 403) return setLoad({ state: "unauthorized" });
      if (!response.ok || !(response.headers.get("content-type") ?? "").includes("json")) return setLoad({ state: "not_connected" });
      try {
        const body: unknown = await response.json();
        if (cancelled) return;
        const items = unwrapList(body).map((r) => parseRef.current(r)).filter((x): x is T => x !== null);
        const next = typeof (body as { next_cursor?: unknown } | null)?.next_cursor === "string" ? (body as { next_cursor: string }).next_cursor : null;
        // Rows that streamed in while the list was loading are kept.
        setLoad((prev) => ({ state: "ok", items: merge(prev.state === "ok" ? prev.items : [], items), next }));
        void stream();
      } catch {
        if (!cancelled) setLoad({ state: "not_connected" });
      }
    })();

    return () => {
      cancelled = true;
      abort.abort();
    };
  }, [enabled, keyValue, attempt, listPath, streamPath, event, pageSize, merge]);

  const more = useCallback(async () => {
    if (load.state !== "ok" || !load.next || moreBusy) return;
    setMoreBusy(true);
    try {
      const response = await fetch(`${listPath}?limit=${pageSize}&cursor=${encodeURIComponent(load.next)}`, { headers: authHeaders(keyValue || undefined), credentials: "same-origin", cache: "no-store" });
      if (!response.ok) return;
      const body: unknown = await response.json();
      const items = unwrapList(body).map((r) => parseRef.current(r)).filter((x): x is T => x !== null);
      const next = typeof (body as { next_cursor?: unknown } | null)?.next_cursor === "string" ? (body as { next_cursor: string }).next_cursor : null;
      setLoad((prev) => (prev.state === "ok" ? { state: "ok", items: merge(prev.items, items), next } : prev));
    } catch {
      /* keep the list; the button stays */
    } finally {
      setMoreBusy(false);
    }
  }, [load, moreBusy, listPath, pageSize, keyValue, merge]);

  return { load, live, more, moreBusy };
}
