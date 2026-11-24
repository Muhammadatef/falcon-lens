"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchVerdict, submitCheck } from "@/lib/api";
import type { Lang, Verdict } from "@/lib/contracts";
import { VERDICT_ID_RE, parseVerdict } from "@/lib/contracts";
import { defang, looksLikeSingleUrl } from "@/lib/defang";
import { MESSAGES, pick } from "@/lib/i18n";
import { voiceText, type VoiceKey } from "@/lib/i18n-voice";
import { usePrefs } from "@/lib/prefs";
import { cancelSpeech, canSpeak, speak } from "@/lib/speech";
import { startListener, voiceSupported, type Listener } from "@/lib/vad";
import {
  PRIVACY_LINE_CONFIRMED,
  aiStepText,
  buildSpeech,
  findIncident,
  buildSummary,
  countOutcomes,
  narMessage,
  narResult,
  narStart,
  newProgressSteps,
  parseVoiceReply,
  sentinelSteps,
  speechLang,
  splitMessages,
  stepKey,
  usedModel,
  voiceBackoffMs,
  topAction,
  topReason,
  totalWords,
  type ClipItem,
  type Outcome,
  type ProgressStep,
  type SentinelIncident,
  type SentinelStep,
  type VoiceReply,
} from "@/lib/voice";
import { spoken, speakArbiter, speakChecking, speakFinal, speakFinding, speakFound, speakHandover, speakMicDenied, speakNothingChecked, speakStep, speakUnavailable, speakVoiceUnavailable, speakWatching } from "@/lib/voice-speech";
import type { SentinelFinding } from "@/lib/voice-script";
import { UntrustedText } from "./Chrome";
import { Icon } from "./Icon";

type Phase = "off" | "starting" | "listening" | "heard" | "checking";
type Problem = "denied" | "unsupported" | "server" | "unavailable" | null;
interface Row {
  key: number;
  item: ClipItem;
  /** null while the check is still running. */
  outcome: Outcome | null;
}
interface Step {
  id: number;
  text: string;
  done: boolean;
  lang: Lang;
}
interface Spoken {
  /** Shown on screen (formal Arabic). */
  text: string;
  /** Spoken aloud (Emirati Arabic / English, from lib/voice-script.ts); defaults to `text`. */
  say?: string;
  lang: Lang;
  /** "msg" lines are dropped when the final summary is queued (the check finished faster than the speech). */
  kind: "msg" | "final";
}

const POLL_MS = 1100;
const POLL_MAX = 45;
const CLIPBOARD_MS = 10_000;
const traceHref = (id: string): string => `/checks/${id}`;

const sleep = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms));

/** Follows one verdict: SSE (each snapshot is reported), then the status URL if the stream drops. Resolves with the final verdict or null. */
function follow(verdictId: string, eventsUrl: string, onSnap: (v: Verdict) => void, alive: () => boolean, signal: AbortSignal): Promise<Verdict | null> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve(null);
    let settled = false;
    let source: EventSource | null = null;
    const finish = (v: Verdict | null) => {
      if (settled) return;
      settled = true;
      source?.close();
      window.clearTimeout(cap);
      resolve(v);
    };
    const cap = window.setTimeout(() => finish(null), 60_000);
    // Stop closes the event stream at once.
    signal.addEventListener("abort", () => finish(null), { once: true });
    const got = (v: Verdict | null) => {
      if (!v || settled) return;
      onSnap(v);
      if (v.final) finish(v);
    };
    const poll = async () => {
      for (let i = 0; i < POLL_MAX && alive() && !settled; i++) {
        try {
          got(await fetchVerdict(verdictId));
        } catch (e) {
          if (!(e instanceof ApiError && e.problem.kind === "not_found")) break;
        }
        if (settled) return;
        await sleep(POLL_MS);
      }
      finish(null);
    };
    try {
      source = new EventSource(eventsUrl);
    } catch {
      void poll();
      return;
    }
    source.addEventListener("verdict", (event) => {
      try {
        got(parseVerdict(JSON.parse(String((event as MessageEvent).data))));
      } catch {
        /* ignore a malformed frame */
      }
    });
    source.onerror = () => {
      source?.close();
      if (!settled) void poll();
    };
  });
}

/** One item through the EXISTING check flow (lib/api.ts): links as links, text as messages; follows its progress. */
async function checkOne(item: ClipItem, onSnap: (v: Verdict) => void, alive: () => boolean, signal: AbortSignal): Promise<Outcome> {
  try {
    const accepted = await submitCheck(item.kind === "url" ? { kind: "url", url: item.text } : { kind: "message", text: item.text });
    if (accepted.verdict) onSnap(accepted.verdict);
    const v = accepted.verdict?.final ? accepted.verdict : await follow(accepted.verdictId, accepted.eventsUrl, onSnap, alive, signal);
    return { id: accepted.verdictId, verdict: v && v.final ? v : null };
  } catch {
    return { id: null, verdict: null };
  }
}

/** Display-only: any link-like word is defanged, and the snippet is short. It is rendered as text, never as a link. */
function snippet(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const out = flat.split(" ").map((w) => (looksLikeSingleUrl(w) ? defang(w) : w)).join(" ");
  return out.length > 110 ? `${out.slice(0, 109)}…` : out;
}

async function readClipboard(): Promise<string | null> {
  if (!navigator.clipboard?.readText) return null;
  try {
    return await Promise.race([navigator.clipboard.readText(), new Promise<null>((r) => window.setTimeout(() => r(null), CLIPBOARD_MS))]);
  } catch {
    return null;
  }
}

const incidentHref = (id: string): string => `/incidents/${id}`;
const SENTINEL_WAIT_MS = 20_000;

type SentinelResult = { kind: "found"; incident: SentinelIncident; steps: SentinelStep[] } | { kind: "timeout" } | { kind: "unavailable" };

/**
 * Polls the public incident list (up to ~20 s) for an incident that links any of our verdict ids, then reads its
 * real LangGraph trace. "timeout" = the route answered but no incident links these checks. "unavailable" = two failed
 * calls in a row, so the Sentinel is not reachable. Never invents an incident.
 */
async function findSentinelIncident(ids: string[], alive: () => boolean, signal: AbortSignal): Promise<SentinelResult> {
  const deadline = Date.now() + SENTINEL_WAIT_MS;
  let misses = 0;
  while (alive() && Date.now() < deadline) {
    try {
      const res = await fetch("/api/public/incidents?limit=50", { cache: "no-store", credentials: "same-origin", signal });
      if (res.ok) {
        const incident = findIncident(await res.json(), ids);
        if (incident) {
          const detail = await fetch(`/api/public/incidents/${incident.id}`, { cache: "no-store", credentials: "same-origin", signal }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
          return { kind: "found", incident, steps: sentinelSteps((detail as { trace?: unknown } | null)?.trace, incident) };
        }
        misses = 0;
      } else if (++misses >= 2) return { kind: "unavailable" };
    } catch {
      if (signal.aborted) return { kind: "timeout" };
      if (++misses >= 2) return { kind: "unavailable" };
    }
    await sleep(2000);
  }
  return { kind: "timeout" };
}

function Tick() {
  return (
    <svg className="voice-tick" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M5 12.5 10 17.5 19 7" />
    </svg>
  );
}

export function VoiceAssistant() {
  const { lang: pageLang, t } = usePrefs();
  const [phase, setPhase] = useState<Phase>("off");
  const [speaking, setSpeaking] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const [voiceActive, setVoiceActive] = useState(false);
  const [level, setLevel] = useState(0);
  const [heard, setHeard] = useState("");
  const [caption, setCaption] = useState("");
  const [stopped, setStopped] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [incident, setIncident] = useState<SentinelIncident | null>(null);
  const [resultLang, setResultLang] = useState<Lang>(pageLang);
  const [showPaste, setShowPaste] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const pasteRef = useRef<HTMLTextAreaElement>(null);

  const listener = useRef<Listener | null>(null);
  const run = useRef(0);
  const langRef = useRef(pageLang);
  langRef.current = pageLang;
  const busy = useRef(false);
  const phaseRef = useRef<Phase>("off");
  phaseRef.current = phase;
  const stepId = useRef(0);
  const queue = useRef<Spoken[]>([]);
  const draining = useRef<Promise<void> | null>(null);
  const drainId = useRef(0);
  const abort = useRef<AbortController | null>(null);
  const failures = useRef(0);
  const lastLang = useRef<"ar" | "en" | null>(null);

  const vt = useCallback((key: VoiceKey, vars?: Record<string, string>) => voiceText(pageLang, key, vars), [pageLang]);

  const addStep = useCallback((text: string, lang: Lang) => {
    setSteps((prev) => [...prev.map((s) => ({ ...s, done: true })), { id: ++stepId.current, text, done: false, lang }]);
  }, []);
  const finishSteps = useCallback(() => setSteps((prev) => prev.map((s) => ({ ...s, done: true }))), []);

  /** Speech queue: one utterance at a time, never overlapping; the caption always shows the line being spoken. */
  const enqueue = useCallback((item: Spoken, token: number) => {
    queue.current.push(item);
    if (draining.current) return;
    const id = ++drainId.current;
    draining.current = (async () => {
      await Promise.resolve();
      while (queue.current.length && run.current === token && drainId.current === id) {
        const next = queue.current.shift()!;
        setCaption(next.text);
        setSpeaking(true);
        await speak(next.say ?? next.text, next.lang, () => run.current === token);
      }
      if (drainId.current === id) {
        setSpeaking(false);
        draining.current = null;
      }
    })();
  }, []);
  const drain = useCallback(async () => {
    while (draining.current) await draining.current;
  }, []);

  /** Shows the line on screen and says it aloud (when the device has a voice for the language). */
  const say = useCallback(
    async (text: string, lang: Lang, token: number, clips?: readonly string[]) => {
      enqueue({ text, say: clips ? spoken(lang, clips) : undefined, lang, kind: "final" }, token);
      await drain();
    },
    [drain, enqueue],
  );

  const backToListening = useCallback((token: number) => {
    if (run.current !== token || !listener.current) return;
    busy.current = false;
    setPhase("listening");
    listener.current.resume();
  }, []);

  const runChecks = useCallback(
    async (text: string, lang: Lang, token: number) => {
      const split = splitMessages(text);
      setTruncated(split.truncated);
      setSteps([]);
      if (!split.items.length) {
        setRows([]);
        await say(voiceText(lang, "voice.say.empty"), lang, token, ["clip.empty"]);
        return;
      }
      const alive = () => run.current === token;
      abort.current?.abort();
      const ctl = new AbortController();
      abort.current = ctl;
      setResultLang(lang);
      setRows(split.items.map((item, key) => ({ key, item, outcome: null })));
      setPhase("checking");
      setCaption("");
      addStep(voiceText(lang, "voice.step.heard", { total: totalWords(lang, split.items.length) }), lang);
      enqueue({ text: narStart(lang, split.items.length), say: speakFound(lang, split.items.length), lang, kind: "msg" }, token);

      const outcomes: Outcome[] = [];
      // One message at a time, so the steps on screen and the narration tell one story in order.
      for (const [at, item] of split.items.entries()) {
        const n = at + 1;
        const start = narMessage(lang, n);
        addStep(start, lang);
        enqueue({ text: start, say: speakChecking(lang, n, split.items.length), lang, kind: "msg" }, token);
        const seen = new Set<ProgressStep>();
        let aiShown = false;
        const outcome = await checkOne(
          item,
          (v) =>
            alive() &&
            newProgressSteps(v, item.kind, seen).forEach((st) => {
              if (st === "ai") {
                const ai = aiStepText(lang, v);
                if (!ai) return;
                aiShown = true;
                addStep(ai, lang);
              } else addStep(voiceText(lang, stepKey(st)), lang);
              const line = speakStep(lang, st, v);
              if (line) enqueue({ text: voiceText(lang, stepKey(st)), say: line, lang, kind: "msg" }, token);
            }),
          alive,
          ctl.signal,
        );
        if (!alive()) return;
        outcomes.push(outcome);
        setRows((prev) => prev.map((r) => (r.key === at ? { ...r, outcome } : r)));
        const v = outcome.verdict;
        // One decision (usedModel) drives screen and speech: a model answered, or the fixed rules decided.
        if (v && !aiShown) {
          if (usedModel(v)) {
            addStep(aiStepText(lang, v) ?? "", lang);
            const line = speakStep(lang, "ai", v);
            if (line) enqueue({ text: aiStepText(lang, v) ?? line, say: line, lang, kind: "msg" }, token);
          } else addStep(voiceText(lang, "investigator.rules_only"), lang);
        }
        addStep(
          v
            ? voiceText(lang, "investigator.arbiter_result", { i: String(n), verdict: MESSAGES[lang][`v.${v.verdict}`], score: String(Math.round(v.risk_score)) })
            : voiceText(lang, "voice.step.failed", { i: String(n) }),
          lang,
        );
        enqueue({ text: narResult(lang, n, v), say: speakArbiter(lang, v), lang, kind: "msg" }, token);
      }

      // Hand over to the Sentinel only if at least one check completed, and look for the REAL incident linking them.
      setIncident(null);
      const done = outcomes.filter((o) => o.verdict && o.id);
      let sentinel: "found" | "watching" | "unavailable" | "none" = "none";
      if (!done.length) {
        const none = voiceText(lang, "voice.nothing_checked");
        addStep(none, lang);
        enqueue({ text: none, say: speakNothingChecked(lang), lang, kind: "final" }, token);
      } else {
        const handover = voiceText(lang, "sentinel.handover");
        addStep(handover, lang);
        enqueue({ text: handover, say: speakHandover(lang), lang, kind: "final" }, token);
        const result = await findSentinelIncident(done.map((o) => o.id as string), alive, ctl.signal);
        if (!alive()) return;
        if (result.kind === "found") {
          sentinel = "found";
          const inc = result.incident;
          setIncident(inc);
          // Screen and speech say exactly what the incident shows: nothing more.
          for (const st of result.steps) addStep(voiceText(lang, `sentinel.${st}` as VoiceKey, { n: String(inc.linked) }), lang);
          const facts: SentinelFinding = { linked: inc.linked, linkStep: result.steps.includes("linked"), summary: result.steps.includes("summary"), drafted: result.steps.includes("draft"), awaiting: result.steps.includes("awaiting_approval") };
          for (const line of speakFinding(lang, facts)) enqueue({ text: line, say: line, lang, kind: "final" }, token);
        } else if (result.kind === "timeout") {
          sentinel = "watching";
          const watching = voiceText(lang, "sentinel.watching");
          addStep(watching, lang);
          enqueue({ text: watching, say: speakWatching(lang), lang, kind: "final" }, token);
        } else {
          sentinel = "unavailable";
          const gone = voiceText(lang, "sentinel.unavailable");
          addStep(gone, lang);
          enqueue({ text: gone, say: speakUnavailable(lang), lang, kind: "final" }, token);
        }
      }
      addStep(buildSummary(lang, countOutcomes(outcomes)), lang);
      // The check may have finished before the narration caught up: the summary replaces any per-message lines still waiting.
      queue.current = queue.current.filter((q) => q.kind === "final"); // keeps the Sentinel lines
      enqueue({ text: buildSpeech(lang, outcomes, { sentinelFound: sentinel === "found" }), say: speakFinal(lang, outcomes, sentinel), lang, kind: "final" }, token);
      await drain();
      if (alive()) finishSteps();
    },
    [addStep, drain, enqueue, finishSteps, say],
  );

  const stopAll = useCallback(() => {
    run.current += 1;
    abort.current?.abort();
    abort.current = null;
    busy.current = false;
    queue.current = [];
    drainId.current += 1;
    draining.current = null;
    cancelSpeech();
    listener.current?.stop();
    listener.current = null;
    setPhase("off");
    setSpeaking(false);
    setVoiceActive(false);
    setLevel(0);
    setCaption("");
    setHeard("");
    setStopped(true);
    finishSteps();
  }, [finishSteps]);

  const onWake = useCallback(
    async (reply: VoiceReply, token: number) => {
      const lang = speechLang(reply.lang, langRef.current);
      if (reply.lang === "ar" || reply.lang === "en") lastLang.current = reply.lang;
      setHeard(reply.transcript);
      setPhase("heard");
      await sleep(450);
      if (run.current !== token) return;
      if (reply.intent === "stop") {
        stopAll();
        void speak(spoken(lang, ["stop"]), lang, () => true);
        return;
      }
      enqueue({ text: voiceText(lang, "voice.state.heard"), say: spoken(lang, ["wake.ack"]), lang, kind: "msg" }, token);
      if (reply.intent === "help") await say(voiceText(lang, "voice.say.help"), lang, token, ["help"]);
      else if (reply.intent === "check_clipboard" || reply.intent === "check_text") {
        const typed = reply.intent === "check_text" ? reply.command.trim() : "";
        const text = typed.length >= 8 ? typed : await readClipboard();
        if (run.current !== token) return;
        if (text === null) {
          setShowPaste(true);
          setRows([]);
          setSteps([]);
          await say(voiceText(lang, "voice.say.paste"), lang, token, ["clip.denied"]);
          pasteRef.current?.focus();
        } else await runChecks(text, lang, token);
      } else await say(voiceText(lang, "voice.say.none"), lang, token, ["didnt"]);
      backToListening(token);
    },
    [backToListening, enqueue, runChecks, say, stopAll],
  );

  /** A voice-service failure: spoken once per streak, shown always, with exponential back-off (1 s, 2 s, 4 s ... 15 s). */
  const voiceFailed = useCallback(
    async (token: number, status: number) => {
      failures.current += 1;
      const first = failures.current === 1;
      setProblem(failures.current >= 2 ? "unavailable" : "server");
      if (failures.current >= 2) setShowPaste(true);
      const l = langRef.current;
      if (first || failures.current === 2) void speak(speakVoiceUnavailable(l), l, () => run.current === token);
      await sleep(status === 429 ? 4000 : voiceBackoffMs(failures.current));
      backToListening(token);
    },
    [backToListening],
  );

  const sendUtterance = useCallback(
    async (audio: Blob, token: number) => {
      if (busy.current) return;
      busy.current = true;
      listener.current?.pause();
      try {
        const form = new FormData();
        form.append("audio", audio, "utterance");
        // Tie-breaker only: the server detects the language per utterance and never forces this one.
        if (lastLang.current) form.append("lang_hint", lastLang.current);
        const res = await fetch("/api/voice", { method: "POST", body: form, credentials: "same-origin", cache: "no-store" });
        if (run.current !== token) return;
        if (!res.ok) return await voiceFailed(token, res.status);
        const reply = parseVoiceReply(await res.json().catch(() => null));
        if (!reply) return await voiceFailed(token, 502);
        failures.current = 0;
        setProblem(null);
        if (reply.transcript) setHeard(reply.transcript);
        if (!reply.wake) return backToListening(token); // not for us: stay quietly in "listening"
        await onWake(reply, token);
      } catch {
        if (run.current === token) await voiceFailed(token, 0);
      }
    },
    [backToListening, onWake, voiceFailed],
  );

  const start = useCallback(async () => {
    setStopped(false);
    setProblem(null);
    failures.current = 0;
    setCaption("");
    setRows([]);
    setSteps([]);
    setIncident(null);
    setHeard("");
    if (!voiceSupported()) {
      setProblem("unsupported");
      setShowPaste(true);
      return;
    }
    const token = ++run.current;
    setPhase("starting");
    // Pre-warm: wake the voice route and the check API, and load both speech voices, so the first command is not slow.
    void fetch("/api/voice", { cache: "no-store" }).catch(() => undefined);
    void fetch("/v1/meta", { cache: "no-store" }).catch(() => undefined);
    void canSpeak("ar");
    void canSpeak("en");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch {
      if (run.current === token) {
        setPhase("off");
        setProblem("denied");
        setShowPaste(true);
        void speak(speakMicDenied(langRef.current), langRef.current, () => true);
      }
      return;
    }
    if (run.current !== token) {
      stream.getTracks().forEach((tr) => tr.stop());
      return;
    }
    listener.current = startListener(stream, { onUtterance: (audio) => void sendUtterance(audio, token), onVoice: setVoiceActive, onLevel: setLevel });
    setPhase("listening");
  }, [sendUtterance]);

  useEffect(
    () => () => {
      run.current += 1;
      abort.current?.abort();
      cancelSpeech();
      listener.current?.stop();
      listener.current = null;
    },
    [],
  );

  // Space forces a capture in a noisy room (not while typing, and not on a focused control, which uses Space itself).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || phaseRef.current !== "listening" || busy.current || e.repeat) return;
      const el = e.target as HTMLElement | null;
      if (el && el.closest("input, textarea, select, button, a, [contenteditable]")) return;
      e.preventDefault();
      setHeard("");
      listener.current?.force();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submitPaste = () => {
    if (!pasteText.trim()) return;
    const token = ++run.current;
    abort.current?.abort();
    cancelSpeech();
    queue.current = [];
    drainId.current += 1;
    draining.current = null;
    busy.current = true;
    void runChecks(pasteText, langRef.current, token).then(() => {
      if (run.current !== token) return;
      busy.current = false;
      if (listener.current) {
        setPhase("listening");
        listener.current.resume();
      } else setPhase("off");
    });
  };

  const done = rows.length > 0 && rows.every((r) => r.outcome);
  const outcomes = rows.flatMap((r) => (r.outcome ? [r.outcome] : []));
  const now = done ? topAction(resultLang, outcomes) : "";
  const shown = speaking ? "speaking" : phase;
  const stateKey: VoiceKey = stopped && phase === "off" ? "voice.state.stopped" : (`voice.state.${shown === "starting" ? "off" : shown}` as VoiceKey);
  const label = phase === "starting" ? vt("voice.mic.starting") : vt(stateKey);
  const active = phase !== "off";

  return (
    <div className="voice" data-testid="voice" data-phase={shown}>
      <section className="card voice-stage" aria-label={vt("voice.region")} data-state={shown} data-voice={voiceActive ? "on" : undefined}>
        <div className="voice-orb" aria-hidden="true">
          <span className="voice-ring" />
          <span className="voice-ring voice-ring--2" />
          <Icon name="mic" size={64} />
        </div>
        <p className="voice-state" role="status" aria-live="polite" data-testid="voice-state">{label}</p>
        {active ? (
          <div className="voice-meter" role="img" aria-label={vt("voice.meter")} data-testid="voice-meter">
            <span className="voice-meter-bar" style={{ transform: `scaleX(${level.toFixed(2)})` }} />
          </div>
        ) : null}
        {heard && active ? (
          <p className="voice-heard" data-testid="voice-heard">
            <span>{vt("voice.heard.label")}</span> <UntrustedText value={heard} />
          </p>
        ) : null}
        {caption ? <p className="voice-say" data-testid="voice-caption" lang={resultLang} dir={resultLang === "ar" ? "rtl" : "ltr"}>{caption}</p> : null}
        <div className="voice-actions">
          {!active ? (
            <button type="button" className="btn btn--primary voice-big" data-testid="voice-on" onClick={() => void start()}>
              <Icon name="mic" size={28} />
              <span>{vt("voice.on")}</span>
            </button>
          ) : null}
          <button type="button" className={active ? "btn voice-big voice-stop" : "btn voice-stop"} data-testid="voice-stop" onClick={stopAll}>
            <Icon name="x" size={active ? 28 : 20} />
            <span>{vt("voice.stop")}</span>
          </button>
        </div>
        {active ? <p className="muted voice-hint">{vt("voice.hint.space")}</p> : null}
      </section>

      {problem ? (
        <p className="paste-error" role="alert" data-testid="voice-problem" data-problem={problem}>
          <Icon name="suspicious" size={24} />
          <span>{vt(problem === "denied" ? "voice.mic.denied" : problem === "unsupported" ? "voice.mic.unsupported" : problem === "unavailable" ? "voice.unavailable.msg" : "voice.server.err")}</span>
        </p>
      ) : null}

      {steps.length ? (
        <section className="card voice-steps" aria-labelledby="voice-steps-h" data-testid="voice-steps">
          <h2 id="voice-steps-h" className="h3">{voiceText(resultLang, "voice.steps.h")}</h2>
          <ol>
            {steps.map((s) => (
              <li key={s.id} data-testid="voice-step" data-done={s.done ? "true" : "false"} lang={s.lang} dir={s.lang === "ar" ? "rtl" : "ltr"}>
                <span className="voice-step-mark">{s.done ? <Tick /> : <span className="voice-dot" />}</span>
                <span>{s.text}</span>
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {showPaste || problem === "denied" || problem === "unsupported" || problem === "unavailable" ? (
        <section className="card voice-paste" aria-labelledby="voice-paste-h" data-testid="voice-paste">
          <h2 id="voice-paste-h" className="h3">{vt("voice.paste.h")}</h2>
          <p className="muted">{vt("voice.paste.hint")}</p>
          <textarea ref={pasteRef} className="voice-paste-box" rows={7} value={pasteText} onChange={(e) => setPasteText(e.target.value)} aria-label={vt("voice.paste.label")} data-testid="voice-paste-input" dir="auto" maxLength={20000} />
          <button type="button" className="btn btn--primary" data-testid="voice-paste-submit" disabled={!pasteText.trim()} onClick={submitPaste}>{vt("voice.paste.btn")}</button>
        </section>
      ) : null}

      {rows.length ? (
        <section className="voice-results" aria-labelledby="voice-res-h" data-testid="voice-results" lang={resultLang} dir={resultLang === "ar" ? "rtl" : "ltr"}>
          <h2 id="voice-res-h" className="h3">{voiceText(resultLang, "voice.res.h")}</h2>
          {truncated ? <p className="muted">{voiceText(resultLang, "voice.res.truncated")}</p> : null}
          {now ? (
            <p className="card voice-todo" data-testid="voice-todo">
              <b>{voiceText(resultLang, "voice.res.todo")}</b>
              <UntrustedText value={now} />
            </p>
          ) : null}
          {incident ? (
            <section className="card voice-sentinel" data-testid="voice-sentinel" data-severity={incident.severity} aria-label={voiceText(resultLang, "voice.sentinel.h")}>
              <h3 className="h3"><Icon name="spark" size={24} /> {voiceText(resultLang, "voice.sentinel.h")}</h3>
              {pick(resultLang, incident.summary) ? <p className="voice-sentinel-title"><UntrustedText value={pick(resultLang, incident.summary)} /></p> : null}
              <p>
                <b>{voiceText(resultLang, "voice.sentinel.sev")}</b> {voiceText(resultLang, `voice.sev.${incident.severity}` as VoiceKey)} · <b>{voiceText(resultLang, "voice.sentinel.count")}</b> {incident.linked}
              </p>
              <p className="voice-sentinel-links">
                <Link className="btn btn--sm" href={incidentHref(incident.id)} data-testid="voice-incident-link">{voiceText(resultLang, "voice.sentinel.open")}</Link>
                <Link className="btn btn--sm" href="/campaigns" data-testid="voice-campaign-link">{voiceText(resultLang, "voice.campaign.link")}</Link>
              </p>
            </section>
          ) : null}
          <ol className="voice-cards">
            {rows.map((r) => {
              const v = r.outcome?.verdict ?? null;
              return (
                <li key={r.key} className="card voice-card" data-testid="voice-card" data-verdict={v?.verdict ?? "pending"}>
                  <div className="voice-card-top">
                    {v ? <Icon name={v.verdict} size={28} /> : <Icon name="clock" size={28} />}
                    <b className="voice-verdict" data-testid="voice-card-verdict">{v ? MESSAGES[resultLang][`v.${v.verdict}`] : r.outcome ? voiceText(resultLang, "voice.res.failed") : voiceText(resultLang, "voice.res.pending")}</b>
                    <span className="muted">{voiceText(resultLang, r.item.kind === "url" ? "voice.res.kind.url" : "voice.res.kind.message")}</span>
                  </div>
                  <p className="voice-snippet" dir="auto" translate="no">{snippet(r.item.text)}</p>
                  {v && topReason(resultLang, v) ? (
                    <p>
                      <b>{voiceText(resultLang, "voice.res.reason")}</b> <UntrustedText value={topReason(resultLang, v)} />
                    </p>
                  ) : null}
                  {v && r.outcome?.id && VERDICT_ID_RE.test(r.outcome.id) ? <Link className="btn btn--sm voice-trace" href={traceHref(r.outcome.id)} data-testid="voice-trace">{voiceText(resultLang, "voice.res.open")}</Link> : null}
                </li>
              );
            })}
          </ol>
        </section>
      ) : null}

      <section className="voice-how" aria-labelledby="voice-how-h">
        <h2 id="voice-how-h" className="h3">{vt("voice.how.h")}</h2>
        <ol>
          <li>{vt("voice.how.1")}</li>
          <li>{vt("voice.how.2")}</li>
          <li>{vt("voice.how.3")}</li>
        </ol>
        <p className="muted">{t("promise")}</p>
        {PRIVACY_LINE_CONFIRMED ? <p className="muted" data-testid="voice-privacy">{vt("voice.privacy")}</p> : null}
      </section>
    </div>
  );
}
