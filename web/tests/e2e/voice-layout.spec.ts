/* eslint-disable @typescript-eslint/no-explicit-any */
import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { dangerousStream } from "../fixtures";
import { VOICE_MESSAGES } from "../../lib/i18n-voice";
import { SCRIPT } from "../../lib/voice-script";
import { expect, newVerdictId, registerScenario, setPrefs, test, token } from "./helpers";

/** Layout of /voice: centred card, caption never squeezed, no overlaps, no horizontal scroll, at every width, language and theme. */
async function mocks(page: Page) {
  for (const lang of ["ar_ae", "en"] as const) {
    const list = Object.entries(SCRIPT[lang]).map(([key, text]) => ({ id: `${lang}.${key}`, file: `${lang}.${key}.mp3`, text, ms: 500, engine: "mock", voice: "mock" }));
    await page.route(`**/voice/${lang}/manifest.json`, (r) => r.fulfill({ json: list }));
    await page.route(new RegExp(`/voice/${lang}/[^/]+\\.mp3$`), (r) => r.fulfill({ contentType: "audio/mpeg", body: "x" }));
  }
  await page.addInitScript(() => {
    const w = window as any;
    w.__level = 0;
    Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } });
    w.AudioContext = class {
      state = "running";
      destination = {};
      decodeAudioData() { return Promise.resolve({}); }
      createBufferSource() { const s: any = { buffer: null, onended: null, connect() {}, stop() {}, start() { setTimeout(() => s.onended?.(), 8); } }; return s; }
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      createAnalyser() { return { fftSize: 1024, connect() {}, getFloatTimeDomainData(b: Float32Array) { b.fill(w.__level); } }; }
      resume() { return Promise.resolve(); }
      close() { return Promise.resolve(); }
    };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { readText: async () => { throw new DOMException("denied", "NotAllowedError"); } } });
  });
}

type Box = { x: number; y: number; width: number; height: number };
const box = async (page: Page, id: string): Promise<Box> => (await page.getByTestId(id).first().boundingBox())!;
const overlap = (a: Box, b: Box) => a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;
const noHScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);

for (const lang of ["ar", "en"] as const) {
  for (const theme of ["dark", "light"] as const) {
    test(`voice layout ${lang} ${theme}: no overlap, caption wide, no horizontal scroll at 390/768/1024/1440/1920`, async ({ page, context, baseURL }) => {
      test.setTimeout(90_000);
      await setPrefs(context, baseURL!, { lang, theme });
      await mocks(page);
      const M = VOICE_MESSAGES[lang];
      for (const width of [390, 768, 1024, 1440, 1920]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/voice");
        await expect(page.getByTestId("voice-state")).toHaveText(M["voice.state.off"]);
        await page.getByTestId("voice-on").click();
        await expect(page.getByTestId("voice-state")).toHaveText(M["voice.state.listening"]);
        await expect(page.getByTestId("voice-clip-chip")).toBeVisible();
        await expect(page.getByTestId("voice-caption")).toBeVisible(); // the greeting
        const card = (await page.locator(".voice-stage").boundingBox())!;
        const mic = (await page.locator(".voice-orb").boundingBox())!;
        const state = await box(page, "voice-state");
        const cap = await box(page, "voice-caption");
        const stop = await box(page, "voice-stop");
        const sfx = await box(page, "voice-sfx");
        const chip = await box(page, "voice-clip-chip");
        const paste = await box(page, "voice-paste");
        if (width >= 1024) expect(cap.width, "caption width vs card").toBeGreaterThanOrEqual(card.width * 0.5);
        expect(cap.height, "caption is not wrapped word by word").toBeLessThan(width >= 768 ? 140 : 200);
        const parts = [mic, state, cap, stop, sfx, chip];
        for (let i = 0; i < parts.length; i++) {
          for (let j = i + 1; j < parts.length; j++) expect(overlap(parts[i]!, parts[j]!), `overlap ${i}/${j} at ${width}`).toBe(false);
          expect(parts[i]!.x, "inside card (start)").toBeGreaterThanOrEqual(card.x - 1);
          expect(parts[i]!.x + parts[i]!.width, "inside card (end)").toBeLessThanOrEqual(card.x + card.width + 1);
        }
        for (const b of [stop, sfx]) expect(b.height).toBeGreaterThanOrEqual(43.5);
        expect(paste.y, "input card below controls").toBeGreaterThanOrEqual(card.y + card.height - 1);
        expect(Math.abs(paste.width - card.width), "same width").toBeLessThan(2);
        expect(Math.abs(mic.x + mic.width / 2 - (card.x + card.width / 2)), "mic centred").toBeLessThan(3);
        expect(await noHScroll(page)).toBe(true);
        if (width === 1440 || width === 390) await page.screenshot({ path: `test-results/voice-layout/${lang}-${theme}-${width}.png`, fullPage: true });
      }
      const axe = await new AxeBuilder({ page }).analyze();
      expect(axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
    });
  }
}

test("voice layout: progress, results and input stay in the same column (en dark, 1440 and 390)", async ({ page, request, context, baseURL }) => {
  test.setTimeout(90_000);
  const t = token();
  const id = newVerdictId();
  await registerScenario(request, { match: `${t}1`, verdictId: id, steps: dangerousStream(id) });
  await setPrefs(context, baseURL!, { lang: "en", theme: "dark" });
  await mocks(page);
  await page.goto("/voice");
  await page.getByTestId("voice-paste-input").fill(`Your account is suspended ${t}1 https://falcon-demo-bank-secure.test/login`);
  await page.getByTestId("voice-paste-submit").click();
  await expect(page.getByTestId("voice-card").first()).toBeVisible({ timeout: 20_000 });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const stage = (await page.locator(".voice-stage").boundingBox())!;
    for (const sel of ["voice-progress", "voice-results", "voice-paste"]) {
      const b = await box(page, sel);
      expect(Math.abs(b.width - stage.width), `${sel} width at ${width}`).toBeLessThan(2);
    }
    expect(await noHScroll(page)).toBe(true);
    await page.screenshot({ path: `test-results/voice-layout/results-en-dark-${width}.png`, fullPage: true });
  }
});
