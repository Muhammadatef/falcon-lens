/* eslint-disable @typescript-eslint/no-explicit-any */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { DEMO_DANGEROUS, buildStream } from "../../lib/demo";
import { dangerousStream, nwsStream, withId } from "../fixtures";
import { VOICE_MESSAGES } from "../../lib/i18n-voice";
import { DEMO_INCIDENT } from "../../lib/demo";
import { DEMO_TRACE } from "../../lib/demo-trace";
import { SCRIPT } from "../../lib/voice-script";
import { expect, newIncidentId, newVerdictId, registerScenario, setPrefs, test, token, useBoards } from "./helpers";

const AR = VOICE_MESSAGES.ar;
const EN = VOICE_MESSAGES.en;

/** Fake microphone, voice-activity input, recorder, clipboard and speech engine (no real audio device is needed). */
async function installMocks(page: Page) {
  await page.addInitScript(() => {
    const w = window as any;
    w.__level = 0;
    w.__voice = "noise";
    w.__tok = Math.random().toString(36).slice(2, 10);
    w.__spoken = [];
    w.__clip = "";
    w.__clipDenied = false;
    w.__gum = 0;
    w.__gumDenied = false;
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          w.__gum += 1;
          if (w.__gumDenied) throw new DOMException("denied", "NotAllowedError");
          return { getTracks: () => [{ stop() {} }] };
        },
      },
    });
    w.AudioContext = class {
      state = "running";
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      createAnalyser() { return { fftSize: 1024, connect() {}, getFloatTimeDomainData(b: Float32Array) { b.fill(w.__level); } }; }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    };
    w.MediaRecorder = class extends EventTarget {
      static isTypeSupported() { return true; }
      start() {}
      stop() {
        const ev: any = new Event("dataavailable");
        ev.data = new Blob([`VOICE:${w.__voice};T:${w.__tok}`], { type: "audio/webm;codecs=opus" });
        this.dispatchEvent(ev);
        this.dispatchEvent(new Event("stop"));
      }
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { readText: async () => { if (w.__clipDenied) throw new DOMException("denied", "NotAllowedError"); return w.__clip; } },
    });
    const voices = [{ name: "Majed", lang: "ar-SA", localService: true }, { name: "Daniel", lang: "en-GB", localService: true }];
    class Utt { text: string; lang = ""; voice: unknown = null; rate = 1; pitch = 1; onend: null | (() => void) = null; onerror: null | (() => void) = null; constructor(t: string) { this.text = t; } }
    w.SpeechSynthesisUtterance = Utt;
    Object.defineProperty(window, "speechSynthesis", {
      configurable: true,
      value: {
        getVoices: () => voices,
        speak(u: Utt) { w.__spoken.push({ text: u.text, lang: u.lang }); setTimeout(() => u.onend?.(), 15); },
        cancel() {},
        addEventListener() {},
        removeEventListener() {},
      },
    });
  });
}

/** Speaks one utterance: loud for ~1 s, then silent until the detector ends it. */
async function say(page: Page, voice: string) {
  await page.evaluate((v) => { (window as any).__voice = v; (window as any).__level = 0.3; }, voice);
  await page.waitForTimeout(1000);
  await page.evaluate(() => { (window as any).__level = 0; });
}

const spoken = (page: Page): Promise<{ text: string; lang: string }[]> => page.evaluate(() => (window as any).__spoken);
/** The narration is a queue of clips with short gaps: wait until the assistant has finished speaking and is listening again. */
const narrationDone = (page: Page) => expect(page.getByTestId("voice")).toHaveAttribute("data-phase", "listening", { timeout: 30_000 });

async function setup(page: Page, request: any) {
  const t = token();
  const ids = [newVerdictId(), newVerdictId(), newVerdictId()];
  const msgs = [
    `Your account is suspended, verify now ${t}1 https://falcon-demo-bank-secure.test/login`,
    `Parcel fee unpaid ${t}2 http://falcon-demo-bank-parcel.test/pay`,
    `Hi, dinner at eight? ${t}3`,
  ];
  await registerScenario(request, { match: `${t}1`, verdictId: ids[0], steps: dangerousStream(ids[0]!) });
  await registerScenario(request, { match: `${t}2`, verdictId: ids[1], steps: dangerousStream(ids[1]!) });
  await registerScenario(request, { match: `${t}3`, verdictId: ids[2], steps: nwsStream(ids[2]!) });
  await installMocks(page);
  await page.addInitScript((clip) => { (window as any).__clip = clip; }, msgs.join("\n\n"));
  return { ids, text: msgs.join("\n\n") };
}

const listening = (lang: typeof AR | typeof EN) => lang["voice.state.listening"];

test.describe("voice assistant: hands-free mode with mocked microphone, clipboard and speech", () => {
  test.setTimeout(120_000);

  test("wake, three messages, live steps in order, spoken in each speaker's language, results and campaign", async ({ page, request }) => {
    const { ids } = await setup(page, request);
    await page.goto("/voice");
    await expect(page.getByTestId("voice-preview")).toBeVisible();
    await expect(page.getByTestId("voice-state")).toHaveText(AR["voice.state.off"]);
    await expect(page.getByTestId("voice-stop")).toBeVisible();
    expect(await page.evaluate(() => (window as any).__gum)).toBe(0); // the mic is never touched before the tap

    await page.getByTestId("voice-on").click();
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR));
    await expect(page.getByTestId("voice-meter")).toBeVisible();

    // Not for us: ignored, stays listening, nothing spoken.
    await say(page, "noise");
    await expect(page.getByTestId("voice-heard")).toContainText("dinner");
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR));
    expect(await spoken(page)).toEqual([]);

    // Arabic speaker.
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-card")).toHaveCount(3);
    await expect(page.getByTestId("voice-todo")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("voice-steps")).toContainText(AR["sentinel.unavailable"], { timeout: 20_000 }); // no Sentinel is connected here: it must say so, not 'still watching'
    const texts = await page.getByTestId("voice-step").allTextContents();
    const at = (needle: string) => texts.findIndex((t) => t.includes(needle));
    const order = [at("سمعتك"), at("يفحص الرسالة الأولى"), at(AR["investigator.lists"]), at("الرسالة 1: حكم"), at("يفحص الرسالة الثانية"), at("الرسالة 3: حكم"), at(AR["sentinel.handover"]), at(AR["sentinel.unavailable"])];
    expect(texts.some((t) => t.includes("المحقّق")) && texts.some((t) => t.includes("«الحارس»"))).toBe(true); // both agents are named on screen
    expect(at(AR["investigator.rules_only"]) >= 0 || at("نظرة ثانية") >= 0).toBe(true); // either the rules decided or a model answered, never silent
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(texts.join(" ")).not.toMatch(/\bT[0-3]\b|آمن|\bsafe\b/i);
    await expect(page.getByTestId("voice-step").first()).toHaveAttribute("data-done", "true");
    await expect(page.getByTestId("voice-card-verdict")).toHaveText(["خطِر", "خطِر", "لم نجد علامات تحذير"]);
    await expect(page.getByTestId("voice-campaign")).toHaveCount(0); // no campaign claim without a real Sentinel incident
    await expect(page.getByTestId("voice-trace").first()).toHaveAttribute("href", `/checks/${ids[0]}`);
    await narrationDone(page);
    const ar = await spoken(page);
    expect(ar.every((s) => s.lang === "ar-SA")).toBe(true);
    const arSpoken = ar.map((s) => s.text).join(" ");
    // No Sentinel is connected in this test: it hands over, then truthfully says it is still watching.
    for (const key of ["wake.ack", "found.3", "investigator.start.1", "investigator.lists", "todo.otp", "sentinel.handover", "sentinel.unavailable", "final.sentinel_unavailable"]) expect(arSpoken, key).toContain(SCRIPT.ar_ae[key]!);
    for (const key of ["sentinel.watching", "final.sentinel_watching", "sentinel.linked.2", "sentinel.linked.3", "sentinel.summary", "sentinel.draft", "sentinel.awaiting_approval", "final.both_agents"]) expect(arSpoken, key).not.toContain(SCRIPT.ar_ae[key]!);
    expect(arSpoken).not.toContain("فحصت"); // the formal screen wording is never the spoken one
    expect(await page.locator("main").innerText()).not.toMatch(/آمن|\bsafe\b/i);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 15_000 });

    // English speaker, same session: answers in English, screen steps switch language too.
    const before = (await spoken(page)).length;
    await say(page, "check-en");
    await expect(page.getByTestId("voice-todo")).toContainText("", { timeout: 25_000 });
    await expect(page.getByTestId("voice-step").first()).toContainText("Heard you: checking three messages from your clipboard");
    await expect(page.getByTestId("voice-card-verdict")).toHaveText(["Dangerous", "Dangerous", "No warning signs found"], { timeout: 25_000 });
    await expect(page.getByTestId("voice-steps")).toContainText(EN["sentinel.unavailable"], { timeout: 20_000 });
    await expect(page.getByTestId("voice-state")).toHaveText(AR["voice.state.listening"], { timeout: 20_000 });
    await narrationDone(page);
    const en = (await spoken(page)).slice(before);
    expect(en.length).toBeGreaterThan(0);
    expect(en.every((s) => s.lang === "en-GB")).toBe(true);
    const enSpoken = en.map((s) => s.text).join(" ");
    for (const key of ["found.3", "investigator.start.1", "sum.dangerous.2", "todo.otp", "sentinel.handover", "final.sentinel_unavailable"]) expect(enSpoken, key).toContain(SCRIPT.en[key]!);
    expect(enSpoken).not.toContain(SCRIPT.en["sentinel.linked.3"]!);
    // Each spoken line is queued, never overlapping: the acknowledgement first, then the count.
    expect(en[0]!.text).toBe(SCRIPT.en["wake.ack"]);

    // Stop works and the mic is released.
    await page.getByTestId("voice-stop").click();
    await expect(page.getByTestId("voice-state")).toHaveText(AR["voice.state.stopped"]);
    await expect(page.getByTestId("voice-on")).toBeVisible();
  });

  test("Sentinel hand-over: a real incident linking these checks gets a card, its trace is narrated, approval is stated", async ({ page, request, context, baseURL }) => {
    const { ids } = await setup(page, request);
    const inc = newIncidentId();
    const trace = { incident_id: inc, thread_id: inc, runs: JSON.parse(JSON.stringify(DEMO_TRACE.runs)) };
    await useBoards(context, request, baseURL!, { incidents: [{ ...DEMO_INCIDENT, incident_id: inc, source: "live", linked_verdicts: ids }], traces: { [inc]: [trace] } });
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-sentinel")).toBeVisible({ timeout: 40_000 });
    await expect(page.getByTestId("voice-incident-link")).toHaveAttribute("href", `/incidents/${inc}`);
    await expect(page.getByTestId("voice-campaign-link")).toHaveAttribute("href", "/campaigns");
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 30_000 });
    const texts = await page.getByTestId("voice-step").allTextContents();
    const at = (needle: string) => texts.findIndex((t) => t.includes(needle));
    const order = [at(AR["sentinel.handover"]), at("ربط «الحارس» 3 بلاغات"), at(AR["sentinel.summary"]), at(AR["sentinel.draft"]), at(AR["sentinel.awaiting_approval"])];
    expect(order.every((i) => i >= 0), JSON.stringify(texts)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(at(AR["sentinel.watching"])).toBe(-1); // never "still watching" when an incident was found
    const said = (await spoken(page)).map((x) => x.text).join(" ");
    for (const key of ["sentinel.handover", "sentinel.linked.3", "sentinel.summary", "sentinel.draft", "sentinel.awaiting_approval", "final.both_agents"]) expect(said, key).toContain(SCRIPT.ar_ae[key]!);
    for (const key of ["sentinel.watching", "final.sentinel_watching"]) expect(said, key).not.toContain(SCRIPT.ar_ae[key]!);
    expect(await page.locator("main").innerText()).not.toMatch(/آمن|\bsafe\b|\bT[0-3]\b/i);
  });

  test("Sentinel timeout: no matching incident means 'still watching', never an invented campaign", async ({ page, request, context, baseURL }) => {
    await setup(page, request);
    await useBoards(context, request, baseURL!, { incidents: [] });
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "check-en");
    await expect(page.getByTestId("voice-steps")).toContainText(EN["sentinel.watching"], { timeout: 70_000 });
    await expect(page.getByTestId("voice-state")).toHaveText(EN["voice.state.listening"], { timeout: 30_000 });
    expect(await page.getByTestId("voice-step").allTextContents()).toContain(EN["sentinel.watching"]);
    await expect(page.getByTestId("voice-sentinel")).toHaveCount(0);
    const said = (await spoken(page)).map((x) => x.text).join(" ");
    for (const key of ["sentinel.handover", "sentinel.watching", "final.sentinel_watching"]) expect(said, key).toContain(SCRIPT.en[key]!);
    for (const key of ["sentinel.linked.3", "sentinel.summary", "sentinel.draft", "sentinel.awaiting_approval", "final.both_agents"]) expect(said, key).not.toContain(SCRIPT.en[key]!);
  });

  test("the AI second look on screen and in speech comes from the same field: a local model answered", async ({ page, request }) => {
    const t = token();
    const id = newVerdictId();
    const steps = buildStream(withId(DEMO_DANGEROUS, id, { model_route: "local" }), [
      { tier: "T0", delayMs: 100, verdict: "no_warning_signs", risk: 22, ms: 40 },
      { tier: "T1", delayMs: 150, verdict: "suspicious", risk: 68, ms: 610 },
    ]);
    await registerScenario(request, { match: t, verdictId: id, steps });
    await installMocks(page);
    await page.addInitScript((c) => { (window as any).__clip = c; }, `Verify your account now ${t} https://falcon-demo-bank-secure.test/login`);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-card")).toHaveCount(1);
    await expect(page.getByTestId("voice-steps")).toContainText(AR["investigator.route.local"], { timeout: 20_000 });
    await expect(page.getByTestId("voice-steps")).not.toContainText(AR["investigator.rules_only"]);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 40_000 });
    const said = (await spoken(page)).map((x) => x.text).join(" ");
    expect(said).toContain(SCRIPT.ar_ae["investigator.ai_second_look_local"]!);
    expect(said).not.toContain(SCRIPT.ar_ae["investigator.rules_only"]!);
  });

  test("nothing checked: no hand-over to the Sentinel, an honest line instead", async ({ page, request }) => {
    await installMocks(page);
    await page.addInitScript(() => { (window as any).__clip = "Unregistered message that the mock cannot check at all"; });
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-steps")).toContainText(AR["voice.nothing_checked"], { timeout: 30_000 });
    await expect(page.getByTestId("voice-steps")).not.toContainText(AR["sentinel.handover"]);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 30_000 });
    const said = (await spoken(page)).map((x) => x.text).join(" ");
    expect(said).toContain(SCRIPT.ar_ae["nothing_checked"]!);
    for (const key of ["sentinel.handover", "sentinel.watching", "sentinel.unavailable", "final.both_agents"]) expect(said, key).not.toContain(SCRIPT.ar_ae[key]!);
    void request;
  });

  test("voice service down: spoken and shown, back-off, then a visible unavailable state with the paste box", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "fail");
    await expect(page.getByTestId("voice-problem")).toHaveAttribute("data-problem", "server");
    await expect.poll(async () => (await spoken(page)).map((x) => x.text).join(" ")).toContain(SCRIPT.ar_ae["voice.unavailable"]!);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 6_000 }); // after ~1 s back-off
    // Under a loaded CI machine the second utterance can land before the mic loop re-arms; retry it
    // (still the same behaviour: repeated failures end in a visible "unavailable" state).
    await expect(async () => {
      await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 6_000 });
      await say(page, "fail");
      await expect(page.getByTestId("voice-problem")).toHaveAttribute("data-problem", "unavailable", { timeout: 4_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByTestId("voice-problem")).toContainText(AR["voice.unavailable.msg"]);
    await expect(page.getByTestId("voice-paste")).toBeVisible();
  });

  test("Stop aborts the running check at once: no steps after Stop", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-steps")).toContainText(AR["investigator.lists"]);
    await page.getByTestId("voice-stop").click();
    await expect(page.getByTestId("voice-state")).toHaveText(AR["voice.state.stopped"]);
    const after = await page.getByTestId("voice-step").count();
    await page.waitForTimeout(3500);
    expect(await page.getByTestId("voice-step").count()).toBe(after);
    await expect(page.getByTestId("voice-card-verdict").first()).toHaveText(AR["voice.res.pending"]);
    await expect(page.getByTestId("voice-sentinel")).toHaveCount(0);
  });

  test("the last detected language is sent as lang_hint", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "help-ar");
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.help"]);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 10_000 });
    await say(page, "none-ar");
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.none"]);
    const tok = await page.evaluate(() => (window as any).__tok as string);
    const calls = ((await (await request.get("/__mock/voice")).json()) as { calls: { marker: string | null; langHint: string | null }[] }).calls.filter((c) => c.marker === tok);
    expect(calls.map((c) => c.langHint)).toEqual([null, "ar"]);
  });

  test("stop intent by voice turns listening off; help and 'just Hey Falcon' are answered aloud", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await say(page, "help-ar");
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.help"]);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 10_000 });
    await say(page, "none-ar");
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.none"]);
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 10_000 });
    expect((await spoken(page)).map((s) => s.text).join(" ")).toContain(SCRIPT.ar_ae["didnt"]!);
    await say(page, "stop");
    await expect(page.getByTestId("voice-state")).toHaveText(AR["voice.state.stopped"]);
    await expect(page.getByTestId("voice-on")).toBeVisible();
  });

  test("clipboard denied: a big paste box appears, Falcon says so aloud, and pasted text is checked", async ({ page, request }) => {
    const { ids, text: msgs } = await setup(page, request);
    await page.goto("/voice");
    await page.evaluate(() => { (window as any).__clipDenied = true; });
    await page.getByTestId("voice-on").click();
    await say(page, "check-ar");
    await expect(page.getByTestId("voice-paste")).toBeVisible();
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.paste"]);
    expect((await spoken(page)).map((s) => s.text).join(" ")).toContain(SCRIPT.ar_ae["clip.denied"]!);
    await page.getByTestId("voice-paste-input").fill(msgs);
    await page.getByTestId("voice-paste-submit").click();
    await expect(page.getByTestId("voice-card")).toHaveCount(3);
    await expect(page.getByTestId("voice-trace").first()).toHaveAttribute("href", `/checks/${ids[0]}`, { timeout: 25_000 });
  });

  test("microphone denied shows the paste box; a failing voice service shows a clear message", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.evaluate(() => { (window as any).__gumDenied = true; });
    await page.getByTestId("voice-on").click();
    await expect(page.getByTestId("voice-problem")).toHaveAttribute("data-problem", "denied");
    await expect.poll(async () => (await spoken(page)).map((x) => x.text).join(" ")).toContain(SCRIPT.ar_ae["mic.denied"]!);
    await expect(page.getByTestId("voice-paste")).toBeVisible();
    await page.evaluate(() => { (window as any).__gumDenied = false; });
    await page.getByTestId("voice-on").click();
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR));
    await say(page, "fail");
    await expect(page.getByTestId("voice-problem")).toHaveAttribute("data-problem", "server");
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR), { timeout: 10_000 });
  });

  test("Space forces a command in a noisy room", async ({ page, request }) => {
    await setup(page, request);
    await page.goto("/voice");
    await page.getByTestId("voice-on").click();
    await expect(page.getByTestId("voice-state")).toHaveText(listening(AR));
    await page.evaluate(() => { (window as any).__voice = "help-ar"; });
    await page.locator("body").press("Space");
    await expect(page.getByTestId("voice-caption")).toHaveText(AR["voice.say.help"], { timeout: 10_000 });
  });

  test("the voice route enforces its limits and the microphone policy is scoped to /voice", async ({ request }) => {
    expect((await request.get("/api/voice")).status()).toBe(200);
    expect((await request.post("/api/voice", { data: { a: 1 } })).status()).toBe(415);
    const bad = await request.post("/api/voice", { multipart: { audio: { name: "a.txt", mimeType: "text/plain", buffer: Buffer.from("hello") } } });
    expect(bad.status(), await bad.text()).toBe(415);
    const ok = await request.post("/api/voice", { multipart: { audio: { name: "a.webm", mimeType: "audio/webm", buffer: Buffer.from("VOICE:noise") } } });
    expect(ok.status()).toBe(200);
    expect(await ok.json()).toMatchObject({ wake: false, intent: "none" });
    expect(JSON.stringify(await ok.json())).not.toContain("test-read-key");
    const voice = await request.get("/voice");
    expect(voice.headers()["permissions-policy"]).toContain("microphone=(self)");
    expect(voice.headers()["content-security-policy"]).not.toMatch(/https?:\/\//);
    expect((await request.get("/")).headers()["permissions-policy"]).toContain("microphone=()");
  });

  test("Home has the big Ask Falcon entry, and the header lists the voice assistant", async ({ page, context, baseURL }) => {
    await setPrefs(context, baseURL!, { lang: "en" });
    await page.goto("/");
    await expect(page.getByTestId("voice-entry")).toContainText("Ask Falcon");
    await expect(page.locator('header nav a[href="/voice"]')).toContainText("Voice assistant");
    await page.getByTestId("voice-entry-cta").click();
    await expect(page).toHaveURL(/\/voice$/);
    await expect(page.locator('header nav a[aria-current="page"]')).toHaveAttribute("href", "/voice");
    await expect(page.getByTestId("voice-state")).toHaveText(EN["voice.state.off"]);
  });

  for (const lang of ["ar", "en"] as const) {
    test(`axe: no serious violations on /voice in ${lang}, idle and with results`, async ({ page, request, context, baseURL }) => {
      await setPrefs(context, baseURL!, { lang });
      await setup(page, request);
      await page.goto("/voice");
      const scan = async () => (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze()).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(await scan()).toEqual([]);
      await page.getByTestId("voice-on").click();
      await say(page, lang === "ar" ? "check-ar" : "check-en");
      await expect(page.getByTestId("voice-todo")).toBeVisible({ timeout: 25_000 });
      await page.waitForTimeout(600);
      expect(await scan()).toEqual([]);
      await page.screenshot({ path: `design/app-shots/voice-${lang}-${page.viewportSize()?.width}.png`, fullPage: true });
    });
  }
});
