"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, fetchVerdict, safeEventsUrl, submitCheck, type CheckInput } from "./api";
import { VERDICT_ID_RE, parseVerdict, type Verdict } from "./contracts";
import { checkReducer, initialCheckState, type CheckInputPreview, type CheckState, type Problem } from "./verdict-stream";

/** Failure path timings (IMPLEMENTATION_PLAN.md §3.4). */
const RETRY_DELAY_MS = 600;
const POLL_INTERVAL_MS = 1200;
const POLL_ATTEMPTS = 5;
const STALL_MS = 60_000;

interface Session {
  token: number;
  source: EventSource | null;
  timers: ReturnType<typeof setTimeout>[];
  abort: AbortController | null;
}

function parseEventData(data: unknown): Verdict | null {
  if (typeof data !== "string") return null;
  try {
    return parseVerdict(JSON.parse(data));
  } catch {
    return null;
  }
}

function setLocationId(id: string | null) {
  const url = new URL(window.location.href);
  for (const key of ["id", "text", "share"]) url.searchParams.delete(key);
  if (id) url.searchParams.set("id", id);
  const next = url.pathname + (url.search ? url.search : "");
  if (next !== window.location.pathname + window.location.search) window.history.pushState(null, "", next);
}

export interface CheckController {
  state: CheckState;
  start: (input: CheckInput, preview: CheckInputPreview) => Promise<void>;
  playDemo: (scene: "danger" | "nws") => Promise<void>;
  reset: () => void;
}

export function useCheck(initialId: string | null): CheckController {
  const [state, dispatch] = useReducer(checkReducer, initialCheckState);
  const session = useRef<Session>({ token: 0, source: null, timers: [], abort: null });

  const stop = useCallback(() => {
    const s = session.current;
    s.token += 1;
    s.source?.close();
    s.source = null;
    s.timers.forEach(clearTimeout);
    s.timers = [];
    s.abort?.abort();
    s.abort = null;
    return s.token;
  }, []);

  /** Follows one verdict: SSE, one reconnect, then polling the status URL, then "interrupted". */
  const follow = useCallback((verdictId: string, eventsUrl: string, token: number) => {
    const s = session.current;
    const alive = () => s.token === token;
    let attempts = 0;
    let done = false;
    let seen = false;
    let lastProblem: Problem | null = null;

    const onVerdict = (v: Verdict) => {
      seen = true;
      dispatch({ type: "verdict", verdict: v });
      if (v.final) {
        done = true;
        s.source?.close();
        s.source = null;
        s.timers.forEach(clearTimeout);
        s.timers = [];
      }
    };

    const poll = async () => {
      s.source?.close();
      s.source = null;
      s.abort = new AbortController();
      for (let i = 0; i < POLL_ATTEMPTS && alive() && !done; i++) {
        try {
          const v = await fetchVerdict(verdictId, s.abort.signal);
          if (!alive()) return;
          lastProblem = null;
          if (v) onVerdict(v);
          if (done) return;
        } catch (error) {
          if (!alive()) return;
          // 404 means "unknown id" or "accepted, nothing published yet": keep polling, decide at the end.
          lastProblem = error instanceof ApiError ? error.problem : null;
        }
        await new Promise<void>((resolve) => s.timers.push(setTimeout(resolve, POLL_INTERVAL_MS)));
      }
      if (!alive() || done) return;
      if (!seen && lastProblem?.kind === "not_found") dispatch({ type: "failed", problem: lastProblem });
      else dispatch({ type: "interrupted" });
    };

    const open = () => {
      if (!alive() || done) return;
      let source: EventSource;
      try {
        source = new EventSource(eventsUrl);
      } catch {
        void poll();
        return;
      }
      s.source = source;
      source.addEventListener("verdict", (event) => {
        if (!alive() || done) return;
        const v = parseEventData((event as MessageEvent).data);
        if (v) onVerdict(v);
      });
      source.onerror = () => {
        if (!alive() || done) return;
        source.close();
        attempts += 1;
        if (attempts <= 1) s.timers.push(setTimeout(open, RETRY_DELAY_MS));
        else void poll();
      };
    };

    s.timers.push(setTimeout(() => { if (alive() && !done) void poll(); }, STALL_MS));
    open();
  }, []);

  const start = useCallback(
    async (input: CheckInput, preview: CheckInputPreview) => {
      const token = stop();
      dispatch({ type: "submit", input: preview });
      try {
        const accepted = await submitCheck(input);
        if (session.current.token !== token) return;
        dispatch({ type: "accepted", verdictId: accepted.verdictId });
        setLocationId(accepted.verdictId);
        if (accepted.verdict) {
          dispatch({ type: "verdict", verdict: accepted.verdict });
          if (accepted.verdict.final) return;
        }
        follow(accepted.verdictId, accepted.eventsUrl, token);
      } catch (error) {
        if (session.current.token !== token) return;
        dispatch({ type: "failed", problem: error instanceof ApiError ? error.problem : { kind: "network", status: 0 } });
      }
    },
    [follow, stop],
  );

  /** Replays a recorded fixture stream. Reachable only from the labelled demo buttons under ?demo=1. */
  const playDemo = useCallback(
    async (scene: "danger" | "nws") => {
      const token = stop();
      const { DEMO_STREAMS } = await import("./demo");
      if (session.current.token !== token) return;
      const steps = DEMO_STREAMS[scene];
      const final = steps[steps.length - 1]?.verdict;
      if (!final) return;
      setLocationId(null);
      dispatch({ type: "submit", input: { kind: "url", text: final.canonical_url ?? "" } });
      dispatch({ type: "accepted", verdictId: final.verdict_id, demo: true });
      let at = 0;
      for (const step of steps) {
        at += step.delayMs;
        session.current.timers.push(
          setTimeout(() => {
            if (session.current.token === token) dispatch({ type: "verdict", verdict: step.verdict });
          }, at),
        );
      }
    },
    [stop],
  );

  const reset = useCallback(() => {
    stop();
    dispatch({ type: "reset" });
    setLocationId(null);
  }, [stop]);

  // Deep link / reload / share target: /?id=vd_… attaches to an existing check.
  useEffect(() => {
    if (!initialId || !VERDICT_ID_RE.test(initialId)) return;
    const token = stop();
    dispatch({ type: "attach", verdictId: initialId });
    follow(initialId, safeEventsUrl(null, initialId), token);
    return () => {
      stop();
    };
  }, [initialId, follow, stop]);

  // Back/forward between "/" and "/?id=…".
  useEffect(() => {
    const onPop = () => {
      const id = new URL(window.location.href).searchParams.get("id");
      const token = stop();
      if (id && VERDICT_ID_RE.test(id)) {
        dispatch({ type: "attach", verdictId: id });
        follow(id, safeEventsUrl(null, id), token);
      } else dispatch({ type: "reset" });
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [follow, stop]);

  return { state, start, playDemo, reset };
}
