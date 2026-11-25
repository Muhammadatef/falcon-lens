/**
 * Renders the main animated architecture to video frames, then to MP4, GIF and PNG with ffmpeg (not assertions):
 *   pnpm build && SHOTS=1 pnpm exec playwright test --project=shots tests/shots/arch-video.shots.ts
 * Output (ARCH_OUT, default <repo>/deliverables/arch, a git-ignored folder):
 *   architecture-<lang>.mp4         1920x1080, 25 fps, no audio
 *   architecture-<lang>-final.png   3840x2160 final frame
 *   architecture-en.gif             960 px wide, for the README (copied to docs/assets/architecture.gif by ARCH_GIF=1)
 * Every frame is seeked exactly (`fl-flow-seek`, plus the Web Animations clock for the build-in), so the result
 * is repeatable. The page chrome is removed for the recording only (bypassCSP is a recording-only setting).
 */
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Browser, Page } from "@playwright/test";
import { setPrefs, test } from "../e2e/helpers";

const OUT = process.env.ARCH_OUT ?? join(process.cwd(), "..", "deliverables", "arch");
const FPS = 25;
const LEAD = 1500;
const TAIL = 1800;
/** Video time runs a little faster than the on-page timeline, to land under 20 seconds. */
const SPEED = 1.18;

const TITLE = { en: "Falcon Lens architecture: one request, three layers", ar: "بنية عدسة الصقر: طلب واحد عبر ثلاث طبقات" } as const;
const CSS = `
  body { padding: 18px 40px 0 !important; }
  .rec-title { font-size: 25px; font-weight: 650; margin: 0 0 10px; color: var(--fl-text); }
  .afc { position: static !important; grid-template-columns: minmax(0, 1fr) !important; padding: 8px 18px !important; }
  .afc-btns, .af-alt, .af-legend { display: none !important; }
  .afc-cap { min-block-size: 0 !important; grid-template-columns: auto minmax(0, 1fr); align-items: baseline; column-gap: 16px; font-size: 19px !important; }
  .afc-count { font-size: 15px !important; }
  .af, .af-stage { gap: 10px !important; }
  .af-band { padding: 8px 16px 12px !important; gap: 8px !important; }
  .af-band-head { grid-template-columns: auto auto minmax(0, 1fr) !important; column-gap: 12px !important; }
  .af-band-head p { grid-column: auto !important; }
  .af-groups { gap: 10px !important; }
  .af-band[data-band="voice"] .af-nodes { grid-template-columns: repeat(6, minmax(0, 1fr)) !important; }
  .af-band[data-band="agents"] .af-groups { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
  .af-band[data-band="agents"] .af-nodes { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
  .af-band[data-band="platform"] .af-groups { grid-template-columns: repeat(3, minmax(0, 1fr)) !important; }
  .af-band[data-band="platform"] .af-nodes { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
  .af[data-step="-1"] .afc-text { visibility: hidden; }
  .af-group[data-titled="true"] { padding: 8px 10px 10px !important; gap: 6px !important; }
  .af-nodes { gap: 9px !important; }
  .af-node { min-height: 3.2rem !important; }
`;

async function stage(browser: Browser, baseURL: string, lang: "ar" | "en", scale: number): Promise<Page> {
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: scale, bypassCSP: true });
  await setPrefs(context, baseURL, { lang, theme: "dark" });
  const page = await context.newPage();
  await page.goto("/docs");
  await page.evaluate(() => document.fonts.ready);
  // Keep only the figure: the recording shows the diagram, not the site chrome.
  await page.evaluate((title) => {
    const fig = document.querySelector('[data-testid="flow-main"]')!;
    const h = document.createElement("p");
    h.className = "rec-title";
    h.textContent = title;
    document.body.replaceChildren(h, fig);
    window.scrollTo(0, 0);
  }, TITLE[lang]);
  await page.addStyleTag({ content: CSS });
  await page.waitForTimeout(400);
  return page;
}

async function seek(page: Page, t: number) {
  await page.evaluate(async (ms) => {
    document.querySelector('[data-testid="flow-main"]')!.dispatchEvent(new CustomEvent("fl-flow-seek", { detail: ms }));
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }, t);
}

for (const lang of ["en", "ar"] as const) {
  test(`architecture video ${lang}`, async ({ browser, baseURL }) => {
    test.setTimeout(600_000);
    mkdirSync(OUT, { recursive: true });
    const frames = mkdtempSync(join(tmpdir(), `fl-arch-${lang}-`));
    const page = await stage(browser, baseURL!, lang, 1);
    const fig = page.getByTestId("flow-main");
    const duration = Number(await fig.getAttribute("data-duration"));
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    if (height > 1080) await page.screenshot({ path: join(OUT, `too-tall-${lang}.png`), fullPage: true });
    if (height > 1080) throw new Error(`the diagram is ${height}px tall at 1920px wide: it must fit one 1080p frame`);

    const step = (1000 / FPS) * SPEED;
    let n = 0;
    for (let t = -LEAD; t <= duration + TAIL; t += step) {
      await seek(page, t);
      if (t < 0) {
        // Build-in: drive the CSS animations by hand so each frame shows the exact moment.
        await page.evaluate((at) => {
          for (const a of document.getAnimations()) {
            a.pause();
            a.currentTime = at;
          }
        }, t + LEAD);
        await page.screenshot({ path: join(frames, `f_${String(n++).padStart(4, "0")}.png`) });
      } else {
        await page.screenshot({ path: join(frames, `f_${String(n++).padStart(4, "0")}.png`), animations: "disabled" });
      }
    }
    const mp4 = join(OUT, `architecture-${lang}.mp4`);
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f_%04d.png"), "-c:v", "libx264", "-preset", "slow", "-crf", "15", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", mp4]);
    if (lang === "en") {
      const gif = join(OUT, "architecture-en.gif");
      for (const [width, fps, colors] of [[960, 10, 96], [880, 8, 64], [800, 6, 48]] as const) {
        execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", join(frames, "f_%04d.png"), "-vf", `fps=${fps},scale=${width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=${colors}:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`, "-loop", "0", gif]);
        if (statSync(gif).size <= 5 * 1024 * 1024) break;
      }
      if (process.env.ARCH_GIF) copyFileSync(gif, join(process.cwd(), "..", "docs", "assets", "architecture.gif"));
    }
    rmSync(frames, { recursive: true, force: true });
    await page.context().close();

    // High-resolution final frame: every step done, the last box lit.
    const still = await stage(browser, baseURL!, lang, 2);
    await seek(still, duration - 10);
    await still.waitForTimeout(600);
    await still.screenshot({ path: join(OUT, `architecture-${lang}-final.png`), animations: "disabled" });
    await still.context().close();
    console.log(`architecture ${lang}: ${n} frames, ${(n / FPS).toFixed(1)} s -> ${mp4}`);
  });
}
