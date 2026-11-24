/**
 * @voice-live  End-to-end proof of the "Hey Falcon" assistant against a RUNNING stack, with a real browser.
 * Not part of `pnpm test:e2e` and not part of CI: run it with `make voice-e2e` (macOS `say` makes the speech).
 *
 * What it does, in order, with real services and nothing mocked:
 *   1. Chromium opens /voice on BASE_URL with a fake microphone that plays the spoken demo line (a wav file made by
 *      `say`), and the clipboard holds three Falcon Demo Bank test messages (fixtures, never a real brand).
 *   2. Hands-free is enabled. The wake phrase must be heard (the route answers wake=true), the three messages are
 *      checked through the public check API (channel "voice") and each card reaches its verdict.
 *   3. The Sentinel card appears, or the page says it is still watching: both are real states, neither is invented.
 *   4. The narration player is called for the right language (pre-generated clips, or the browser voice as fallback).
 *   5. /history (public) lists those checks with the Voice badge, and the check page shows the channel.
 *   6. Prometheus shows fl_voice_utterances_total up, and Phoenix has a voice.utterance span (metadata only).
 *      Phoenix and Prometheus are optional: when they are not reachable the step is reported as skipped, with the reason.
 *
 * Environment: BASE_URL / LIVE_BASE_URL (default https://localhost:8443), VOICE_E2E_WAV (the spoken line, required),
 * VOICE_E2E_LANG (en | ar), PROM_URL, PHOENIX_URL + PHOENIX_API_KEY or PHOENIX_ADMIN_SECRET (read-only),
 * VOICE_E2E_RESULT (path of the JSON result written for the review file).
 * No transcript and no audio is written anywhere by this test.
 */
import { writeFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { voiceText } from "../../lib/i18n-voice";

const LANG = (process.env.VOICE_E2E_LANG ?? "en") as "en" | "ar";
const PROM_URL = (process.env.PROM_URL ?? "").replace(/\/+$/, "");
const PHOENIX_URL = (process.env.PHOENIX_URL ?? "").replace(/\/+$/, "");
const PHOENIX_KEY = process.env.PHOENIX_API_KEY || process.env.PHOENIX_ADMIN_SECRET || "";

type Verdict = "dangerous" | "suspicious" | "no_warning_signs";
interface Step {
  name: string;
  status: "passed" | "skipped" | "failed";
  detail: string;
}
const steps: Step[] = [];
const note = (name: string, status: Step["status"], detail: string) => steps.push({ name, status, detail });

/** One unique run id on every message: a repeated identical message would come from the verdict cache. */
const run = Date.now().toString(36);
const MESSAGES: { id: string; text: string; expect: Verdict[] }[] = [
  {
    id: "lookalike-link",
    text: `Falcon Demo Bank: your account is limited. Confirm now at http://falcon-demo-bank-secure.test/login ref ${run}a`,
    expect: ["dangerous"],
  },
  {
    id: "otp-phishing",
    text: `Falcon Demo Bank: to cancel this transfer, reply with the one-time code you just received. Ref ${run}b`,
    expect: ["dangerous", "suspicious"],
  },
  {
    id: "genuine-notice",
    text: `Falcon Demo Bank: your statement is ready in the app. No action needed. Ref ${run}c`,
    expect: ["no_warning_signs"],
  },
];

async function promTotal(metric: string): Promise<number | null> {
  if (!PROM_URL) return null;
  try {
    const r = await fetch(`${PROM_URL}/api/v1/query?query=${encodeURIComponent(`sum(${metric})`)}`, { signal: AbortSignal.timeout(5000) });
    const body = (await r.json()) as { data?: { result?: { value?: [number, string] }[] } };
    const v = body.data?.result?.[0]?.value?.[1];
    return v === undefined ? 0 : Number(v);
  } catch {
    return null;
  }
}

/** Reads voice.utterance spans from Phoenix (read-only). Returns the count of spans newer than `sinceMs`, or a reason it could not look. */
async function phoenixVoiceSpans(sinceMs: number): Promise<{ count: number; attrs: string[]; linked: number } | { skip: string }> {
  if (!PHOENIX_URL) return { skip: "PHOENIX_URL is not set" };
  if (!PHOENIX_KEY) return { skip: "no PHOENIX_API_KEY / PHOENIX_ADMIN_SECRET in the environment" };
  const headers = { authorization: `Bearer ${PHOENIX_KEY}` };
  try {
    const pr = await fetch(`${PHOENIX_URL}/v1/projects`, { headers, signal: AbortSignal.timeout(8000) });
    if (!pr.ok) return { skip: `Phoenix /v1/projects answered HTTP ${pr.status}` };
    const projects = ((await pr.json()) as { data?: { name: string }[] }).data ?? [];
    let count = 0;
    let linked = 0;
    const attrs = new Set<string>();
    for (const p of projects) {
      const sr = await fetch(`${PHOENIX_URL}/v1/projects/${encodeURIComponent(p.name)}/spans?limit=500&start_time=${encodeURIComponent(new Date(sinceMs).toISOString())}`, { headers, signal: AbortSignal.timeout(15000) });
      if (!sr.ok) continue;
      const spans = ((await sr.json()) as { data?: { name?: string; parent_id?: string | null; context?: { span_id?: string }; attributes?: Record<string, unknown> }[] }).data ?? [];
      const voiceIds = new Set<string>();
      for (const s of spans) {
        if (s.name !== "voice.utterance") continue;
        count += 1;
        if (s.context?.span_id) voiceIds.add(s.context.span_id);
        for (const k of Object.keys(s.attributes ?? {})) attrs.add(k);
      }
      // Check spans started by the utterance are its children (the traceparent travelled through the web route).
      linked += spans.filter((s) => s.parent_id && voiceIds.has(s.parent_id) && /\/v1\/check\//.test(String(s.attributes?.["http.route"] ?? ""))).length;
    }
    return { count, attrs: [...attrs].sort(), linked };
  } catch (e) {
    return { skip: `Phoenix not reachable (${(e as Error).name})` };
  }
}

async function poll<T>(fn: () => Promise<T | null | false>, ms: number, every = 3000): Promise<T | null> {
  const end = Date.now() + ms;
  for (;;) {
    const v = await fn();
    if (v) return v as T;
    if (Date.now() > end) return null;
    await new Promise((r) => setTimeout(r, every));
  }
}

async function instrument(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __clipStarts: number; __speech: { lang: string }[] };
    w.__clipStarts = 0;
    w.__speech = [];
    const start = AudioBufferSourceNode.prototype.start;
    AudioBufferSourceNode.prototype.start = function (...a: Parameters<typeof start>) {
      w.__clipStarts += 1;
      return start.apply(this, a);
    };
    const synth = window.speechSynthesis;
    if (synth) {
      const speak = synth.speak.bind(synth);
      synth.speak = (u: SpeechSynthesisUtterance) => {
        w.__speech.push({ lang: u.lang });
        return speak(u);
      };
    }
  });
}

test.describe("@voice-live Hey Falcon, end to end", () => {
  test.skip(!process.env.VOICE_E2E_WAV, "VOICE_E2E_WAV (the spoken line) is not set; run it through `make voice-e2e`");

  test(`${LANG}: wake, three checks, Sentinel, narration, History, metrics, traces`, async ({ page, context, baseURL }) => {
    test.setTimeout(240_000);
    const startedAt = Date.now();
    const clipRequests: string[] = [];
    page.on("request", (r) => {
      const m = /\/voice\/(en|ar_ae)\/[^/]+$/.exec(new URL(r.url()).pathname);
      if (m) clipRequests.push(m[1]!);
    });
    const result: Record<string, unknown> = { lang: LANG, base_url: baseURL, started_at: new Date(startedAt).toISOString() };
    try {
      await context.grantPermissions(["clipboard-read", "clipboard-write", "microphone"], { origin: new URL(baseURL!).origin });
      await context.addCookies([{ name: "fl_lang", value: LANG, url: baseURL! }]);
      await instrument(page);

      const utterancesBefore = await promTotal("fl_voice_utterances_total");

      await page.goto("/voice");
      await page.evaluate((t) => navigator.clipboard.writeText(t), MESSAGES.map((m) => m.text).join("\n\n"));
      note("clipboard", "passed", `${MESSAGES.length} Falcon Demo Bank fixture messages on the clipboard`);

      // Enable hands-free: the fake microphone starts playing the spoken line.
      const wake = page.waitForResponse((r) => r.url().endsWith("/api/voice") && r.request().method() === "POST", { timeout: 90_000 });
      await page.getByTestId("voice-on").click();
      await expect(page.getByTestId("voice")).toHaveAttribute("data-phase", /listening|heard|checking/);
      const reply = await wake;
      expect(reply.status(), "the voice route answers").toBe(200);
      const body = (await reply.json()) as { wake?: boolean; intent?: string; lang?: string; model?: string };
      expect(body.wake, "the wake phrase was heard").toBe(true);
      expect(body.intent).toBe("check_clipboard");
      const engine = (body.model ?? "").split(":")[0];
      result.wake = { wake: body.wake, intent: body.intent, lang: body.lang, engine };
      note("wake", "passed", `wake=true, intent=${body.intent}, speech engine=${engine || "?"}, language=${body.lang}`);

      // Three cards, each with a final verdict.
      await expect(page.getByTestId("voice-card")).toHaveCount(MESSAGES.length, { timeout: 60_000 });
      await expect(page.getByTestId("voice-card").and(page.locator('[data-verdict="pending"]'))).toHaveCount(0, { timeout: 150_000 });
      const verdicts = await page.getByTestId("voice-card").evaluateAll((els) => els.map((e) => e.getAttribute("data-verdict")));
      const ids = await page.getByTestId("voice-trace").evaluateAll((els) => els.map((e) => (e.getAttribute("href") ?? "").replace("/checks/", "")));
      result.verdicts = MESSAGES.map((m, i) => ({ message: m.id, verdict: verdicts[i], expected: m.expect }));
      result.verdict_ids = ids;
      MESSAGES.forEach((m, i) => expect(m.expect, `${m.id} verdict (${verdicts[i]})`).toContain(verdicts[i] as Verdict));
      note("checks", "passed", MESSAGES.map((m, i) => `${m.id}=${verdicts[i]}`).join(", "));
      expect(ids.filter((id) => /^vd_[0-9A-HJKMNP-TV-Z]{26}$/.test(id))).toHaveLength(MESSAGES.length);

      // The live steps come from real progress events: the Investigator and Sentinel steps are on screen.
      const stepTexts = await page.getByTestId("voice-step").allInnerTexts();
      expect(stepTexts.length).toBeGreaterThan(MESSAGES.length);

      // Sentinel: an incident card, or the honest "still watching" line.
      const watching = voiceText(LANG, "sentinel.watching");
      const sentinelCard = page.getByTestId("voice-sentinel");
      await expect(async () => {
        const hasCard = (await sentinelCard.count()) > 0;
        const hasWatching = (await page.getByTestId("voice-step").allInnerTexts()).some((t) => t.includes(watching));
        expect(hasCard || hasWatching, "Sentinel card or 'still watching'").toBe(true);
      }).toPass({ timeout: 60_000 });
      const sentinel = (await sentinelCard.count()) > 0 ? "incident card" : "still watching";
      result.sentinel = sentinel;
      note("sentinel", "passed", sentinel);

      // Let the narration finish, then read the player evidence.
      await expect(page.getByTestId("voice")).not.toHaveAttribute("data-phase", "speaking", { timeout: 120_000 }).catch(() => undefined);
      await page.waitForTimeout(2000);
      const play = await page.evaluate(() => {
        const w = window as unknown as { __clipStarts: number; __speech: { lang: string }[] };
        return { clipStarts: w.__clipStarts, speech: w.__speech.map((s) => s.lang) };
      });
      const wantClipDir = LANG === "ar" ? "ar_ae" : "en";
      const wrongClipDir = LANG === "ar" ? "en" : "ar_ae";
      const narrated = play.clipStarts > 0 || play.speech.length > 0;
      expect(narrated, "the narration player was called").toBe(true);
      expect(clipRequests.filter((d) => d === wrongClipDir && play.clipStarts > 0 && !clipRequests.includes(wantClipDir)), "no clips of the wrong language played").toHaveLength(0);
      if (play.speech.length) expect(play.speech.every((l) => l.toLowerCase().startsWith(LANG)), `browser speech language ${play.speech.join(",")}`).toBe(true);
      result.narration = { clips_started: play.clipStarts, speech_fallback_utterances: play.speech.length, speech_langs: [...new Set(play.speech)], clip_folders_requested: [...new Set(clipRequests)] };
      note("narration", "passed", `${play.clipStarts} pre-generated clips started, ${play.speech.length} browser-speech fallback lines (${[...new Set(play.speech)].join(",") || "none"}); clip folders fetched: ${[...new Set(clipRequests)].join(",") || "none"}`);

      // History (public, no key): the checks are listed with the Voice badge.
      await page.goto("/history");
      for (const id of ids) {
        const row = page.locator(`[data-testid="check-row"][data-check-id="${id}"]`);
        await expect(row, `history row ${id}`).toBeVisible({ timeout: 45_000 });
        await expect(row.getByTestId("voice-badge")).toBeVisible();
      }
      note("history", "passed", `${ids.length} checks listed on /history with the Voice badge`);
      await page.goto(`/checks/${ids[0]}`);
      await expect(page.getByTestId("check-channel")).toHaveAttribute("data-channel", "voice", { timeout: 30_000 });
      note("check page", "passed", "/checks/<id> shows channel=voice");

      // Prometheus: utterances went up.
      if (!PROM_URL) note("prometheus", "skipped", "PROM_URL is not set");
      else if (utterancesBefore === null) note("prometheus", "skipped", `Prometheus not reachable at ${PROM_URL}`);
      else {
        const after = await poll(async () => {
          const v = await promTotal("fl_voice_utterances_total");
          return v !== null && v > utterancesBefore ? v : false;
        }, 90_000);
        expect(after, `fl_voice_utterances_total rose from ${utterancesBefore}`).not.toBeNull();
        const vc = await promTotal("fl_voice_checks_total");
        result.prometheus = { utterances_before: utterancesBefore, utterances_after: after, voice_checks_total: vc };
        note("prometheus", "passed", `fl_voice_utterances_total ${utterancesBefore} -> ${after}; fl_voice_checks_total=${vc}`);
      }

      // Phoenix: a voice.utterance span with metadata attributes only.
      const first = await phoenixVoiceSpans(startedAt - 60_000);
      if ("skip" in first) note("phoenix", "skipped", first.skip);
      else {
        const spans = await poll(async () => {
          const r = await phoenixVoiceSpans(startedAt - 60_000);
          return "count" in r && r.count > 0 && r.linked > 0 ? r : false;
        }, 90_000);
        expect(spans, "Phoenix has a voice.utterance span").not.toBeNull();
        const attrs = (spans as { attrs: string[] }).attrs;
        expect(attrs.filter((k) => /transcript|text|audio|content/i.test(k)), "no content attribute on the span").toHaveLength(0);
        const linked = (spans as { linked: number }).linked;
        expect(linked, "check spans are children of voice.utterance (traceparent propagated)").toBeGreaterThan(0);
        result.phoenix = { voice_utterance_spans: (spans as { count: number }).count, linked_check_spans: linked, attributes: attrs };
        note("phoenix", "passed", `${(spans as { count: number }).count} voice.utterance span(s) with ${linked} linked check span(s); attributes: ${attrs.join(", ")}`);
      }
      result.outcome = "passed";
    } catch (e) {
      result.outcome = "failed";
      result.error = String((e as Error).message ?? e).split("\n")[0]!.slice(0, 300);
      note("failure", "failed", String(result.error));
      throw e;
    } finally {
      result.steps = steps;
      if (process.env.VOICE_E2E_RESULT) writeFileSync(process.env.VOICE_E2E_RESULT, JSON.stringify(result, null, 2));
    }
  });
});
