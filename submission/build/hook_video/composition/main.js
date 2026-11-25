// The director. Builds the stage once, then window.__seek(t) draws the film at time t (seconds) and resolves
// when the frame is ready to be captured. Input: window.__HOOK__ = {timeline, data, format, options}.
import { C, E, TAU, clamp, h, mix, mixc, put, seg, track, tw, win } from "./lib.js";
import { APERTURE, makeLens } from "./lens.js";
import { makeBackdrop, makeFx } from "./stage.js";
import { makeCaptions, makeLabel, makeLive } from "./hud.js";
import * as Message from "./scene_message.js";
import * as Checks from "./scene_checks.js";
import * as Verdict from "./scene_verdict.js";
import * as Full from "./scene_full.js";

const HOOK = window.__HOOK__;
const TL = HOOK.timeline;
const D = HOOK.data;
const opts = HOOK.options ?? {};
const portrait = HOOK.format === "portrait";

// Where things sit, per format. The stage is a 1000 x 1000 box the scenes are written in.
const L = portrait
  ? {
      W: 1080, H: 1920, portrait,
      stage: { x: 40, y: 190, s: 1 },
      text: { x: 64, w: 952, activeTop: 1482, ar: 60, en: 32, tag: 27, num: 50, gap: 16 },
      live: { x: 0, y: 0, w: 1080, h: 1300, srcY: 0, fade0: 1010 },
      chip: { x: 636, y: 44, w: 400, h: 72, font: 28 },
      full: {
        cx: 540, introY: 800, introS: 1.3, introWord: 76, introWordY: 1215,
        endY: 560, endS: 0.7, endWord: 60, endWordY: 870, endTag: 82, endTagY: 1065, endEn: 40, endEnY: 1170,
        endSite: 46, endSiteY: 1300, endEvent: 27, endEventY: 1402, endSmall: 23.5, endSmallW: 940, endSmallY: 1690,
      },
    } // prettier-ignore
  : {
      W: 1920, H: 1080, portrait,
      stage: { x: 50, y: 40, s: 1 },
      text: { x: 1130, w: 730, activeTop: 440, ar: 50, en: 27, tag: 23, num: 42, gap: 14 },
      live: { x: 0, y: 0, w: 1080, h: 1080, srcY: 118, fade0: 0 },
      chip: { x: 1524, y: 38, w: 356, h: 62, font: 25 },
      full: {
        cx: 960, introY: 430, introS: 1.0, introWord: 78, introWordY: 770,
        endY: 215, endS: 0.5, endWord: 46, endWordY: 388, endTag: 90, endTagY: 530, endEn: 34, endEnY: 622,
        endSite: 36, endSiteY: 720, endSiteX: 800, endEvent: 22, endEventY: 720, endEventX: 1130, endSmall: 19.5, endSmallW: 1500, endSmallY: 915,
      },
    }; // prettier-ignore

const frame = document.getElementById("frame");
frame.style.width = `${L.W}px`;
frame.style.height = `${L.H}px`;
const stage = document.getElementById("stage");
const world = document.getElementById("world");
const hud = document.getElementById("hud");
const full = document.getElementById("full");
const flashEl = document.getElementById("flash");
const cam = { dx: 0, dy: 0 };
const P = (x, y) => [L.stage.x + cam.dx + x * L.stage.s, L.stage.y + cam.dy + y * L.stage.s];
const sc = (id) => TL.scenes.find((s) => s.id === id) ?? null;
const mark = (name) => TL.marks[name];
const line = (id) => TL.lines.find((l) => l.id === id) ?? null;
const env = TL.env ?? { voice: [], live: [], music: [], low: [], bands: [] };
const at = (arr, t) => arr[clamp(Math.round(t * TL.fps), 0, arr.length - 1)] ?? 0;
/** A level with a short release, so bars fall instead of flickering. */
const smooth = (arr, t) => Math.max(at(arr, t), 0.72 * at(arr, t - 1 / TL.fps), 0.45 * at(arr, t - 2 / TL.fps), 0.25 * at(arr, t - 3 / TL.fps));

let flashes = [];
const flashAdd = (o, bg) => o > 0.004 && flashes.push([o, bg]);

async function boot() {
  await Promise.all([
    document.fonts.load('650 40px "Readex Pro Variable"', "عدسة الصقر"),
    document.fonts.load('400 40px "Readex Pro Variable"', "Falcon Lens"),
    document.fonts.load('650 40px "Readex Pro Variable"', "Falcon Lens"),
    document.fonts.load('600 24px "JetBrains Mono Variable"', "hxxp://0123456789abcdef[.]test"),
  ]);
  await document.fonts.ready;

  const backdrop = makeBackdrop(document.getElementById("bg"), L);
  const fx = makeFx(document.getElementById("fx"), L);
  const live = makeLive(document.getElementById("live"), L, TL, opts);
  const lens = makeLens(world);
  const label = makeLabel(document.getElementById("chip"), L, D.label);

  const intro = sc("intro");
  const cold = sc("cold");
  const wake = sc("wake");
  const listen = sc("listen");
  const found = sc("found");
  const baseer = sc("baseer");
  const lists = sc("lists");
  const address = sc("address");
  const page = sc("page");
  const ai = sc("ai");
  const verdict = sc("verdict");
  const dir = sc("dir");
  const todo = sc("todo");
  const relief = sc("relief");
  const end = sc("end");
  const snap = mark("wake.snap");
  const markIn = mark("mark.in");
  const say = mark("wake.say");
  const converge = mark("verdict.converge");
  const slam = mark("verdict.slam");
  const film = TL.variant !== "intro";

  // ── The lens path, in frame pixels: [x, y, scale] ──────────────────────────────────────────────
  const F = L.full;
  const toFrame = ([x, y, s]) => [L.stage.x + x * L.stage.s, L.stage.y + y * L.stage.s, s * L.stage.s];
  const keys = [{ t: 0, d: 0, v: [F.cx, F.introY, F.introS] }];
  const K = (t, d, v, e) => keys.push({ t, d, v: toFrame(v), e });
  const ctx = { stage, full, TL, D, L, P, fx, sc, mark, line, lens, flashAdd, lensPos: null, message: null };
  let lensTrack = () => keys[0].v;
  ctx.lensPos = (t) => {
    const [x, y, s] = lensTrack(t);
    return { x: (x - L.stage.x) / L.stage.s, y: (y - L.stage.y) / L.stage.s, s: s / L.stage.s };
  };
  const message = film ? Message.build(ctx) : null;
  ctx.message = message;
  const checks = film ? Checks.build(ctx) : null;
  const verdictScene = film ? Verdict.build(ctx) : null;
  const fullScene = Full.build(ctx);
  if (film) {
    K(markIn, 0, [500, 505, 0.92]);
    K(snap + 0.5, 0.5, [500, 500, 1.06], E.spring);
    K(found.t0 + 0.4, 0.5, [500, 252, 0.6]);
    const cs = Message.CARD.foundScale;
    const [fx0, fy0] = Message.CARD.found;
    K(baseer.t0 + 0.55, 0.5, [fx0 + 220, fy0 - 70, 0.62]);
    K(baseer.t0 + 1.12, 0.52, [fx0 - 150, fy0 + 10, 0.62], E.io2);
    K(baseer.t1 - 0.1, 0.42, [fx0 + message.linkAt[0] * cs, fy0 + message.linkAt[1] * cs, 0.62], E.io3);
    K(lists.t0 + 0.42, 0.45, [500, 262, 0.64]);
    K(address.t0 + 0.3, 0.38, [150, Checks.ADDR.lensY, 0.5]);
    K(address.t0 + 1.3, 1.0, [850, Checks.ADDR.lensY, 0.5], E.io2);
    K(address.t0 + 1.9, 0.3, [checks.addedX, Checks.ADDR.lensY - 6, 0.52], E.outE);
    K(page.t0 + 0.45, 0.5, [848, 188, 0.46]);
    K(ai.t0 + 0.45, 0.5, [500, 258, 0.7]);
    K(converge + 0.45, 0.45, [500, 338, 0.8]);
    K(slam + 0.5, 0.5, [500, 330, 0.94], E.spring);
    K(dir.t0 + 0.6, 0.6, [215, 215, 0.4]);
    K(todo.t0 + 0.6, 0.6, [500, 196, 0.46]);
    keys.push({ t: end.t0 + 0.5, d: 0.5, v: [F.cx, F.endY, F.endS], e: E.io3 });
  }
  lensTrack = track(keys);

  const captions = film ? makeCaptions(hud, L, TL, D.speakers) : { update() {} };

  // Status line under the lens, the product's own wording (web/lib/i18n-voice.ts).
  const statusOf = (ar, en) => h("div.at", {}, h("div.c", {}, h("div.status", { dir: "rtl" }, h("span", { text: ar }), h("small", { text: en }))));
  const stListen = statusOf("أستمع إليك… قل: «يا صقر»", "Listening… say “Hey Falcon”");
  const stHeard = statusOf("سمعتك", "Heard you");
  const stCheck = statusOf("أفحص رسائلك الآن…", "Checking your messages…");
  if (film) stage.append(stListen, stHeard, stCheck);

  const blinks = film ? [snap + 0.75, found.t0 + 0.12, address.t0 + 1.66, ai.t0 + 1.4, todo.t0 + 0.95, todo.t1 - 0.6] : [];
  const tiers = film ? [lists, address, page, ai] : [];

  function lensState(t) {
    const [x, y, s] = lensTrack(t);
    const st = { x: x + cam.dx, y: y + cam.dy, scale: s, color: C.brand, gaze: [0, 0], arcs: [0, 0, 0, 0], run: -1 };
    if (t < (intro?.t1 ?? 0) && (!film || t < intro.t1)) {
      // Logo sting: strokes draw in the dark, snap into focus on the first hit.
      const h1 = mark("intro.hit1");
      const h2 = mark("intro.hit2");
      const out = film ? E.in3(seg(t, mark("intro.out"), intro.t1)) : 0;
      st.m = 0;
      st.o = tw(t, 0.15, 0.35, E.out2) * (film ? 1 : 1 - E.in2(seg(t, intro.t1 - 0.4, intro.t1 - 0.04)));
      st.draw = E.io2(seg(t, 0.28, h1 - 0.06));
      st.markPupil = tw(t, h1, 0.4, E.spring);
      st.markDim = mix(0.5, 1, tw(t, h1, 0.1));
      st.blur = mix(13, 5, seg(t, 0.2, h1)) * (1 - tw(t, h1, 0.1)) + 26 * out;
      const pop = E.bump(seg(t, mark("intro.tap1"), mark("intro.tap1") + 0.26), 0.25) * 0.035 + E.bump(seg(t, mark("intro.tap2"), mark("intro.tap2") + 0.26), 0.25) * 0.045 + E.bump(seg(t, h2, h2 + 0.45), 0.2) * 0.07;
      st.scale = s * (mix(1.26, 1.18, seg(t, 0, h1)) * (1 - tw(t, h1, 0.5, E.spring)) + tw(t, h1, 0.5, E.spring) + pop) * (1 + 21 * out);
      st.glow = 0.5 + 1.6 * E.bump(seg(t, h1, h1 + 0.8), 0.1) + 1.2 * E.bump(seg(t, h2, h2 + 0.8), 0.1);
      return st;
    }
    if (!film) return { ...st, o: 0 };
    if (t < markIn) return { ...st, o: 0 };
    // Mark to instrument at the wake; back to the mark for the end card.
    const awake = tw(t, snap, 0.36, E.out3);
    const closing = tw(t, end.t0 + 0.02, 0.45, E.io3);
    st.m = awake * (1 - closing);
    st.o = tw(t, markIn, 0.4, E.out2);
    st.draw = 1;
    st.markPupil = 1;
    st.markDim = mix(0.62, 1, clamp(awake + seg(t, say, say + 0.3)));
    st.blink = Math.max(...blinks.map((b) => E.bump(seg(t, b, b + 0.2), 0.45)));
    // Aperture: asleep, listening, working, shut before the verdict, locked on it.
    let ap = track([
      { t: snap, d: 0, v: APERTURE.shut },
      { t: snap + 0.55, d: 0.55, v: APERTURE.listen, e: E.spring },
      { t: found.t0 + 0.3, d: 0.3, v: APERTURE.idle },
      { t: baseer.t0 + 0.5, d: 0.4, v: APERTURE.wide, e: E.out3 },
      { t: lists.t0 + 0.4, d: 0.4, v: APERTURE.scan },
      { t: page.t0 + 0.4, d: 0.4, v: 58 },
      { t: ai.t0 + 0.4, d: 0.4, v: APERTURE.think },
      { t: slam - 0.04, d: slam - converge - 0.06, v: APERTURE.shut, e: E.in2 },
      { t: slam + 0.45, d: 0.45, v: APERTURE.locked, e: E.spring },
      { t: todo.t0 + 0.7, d: 0.6, v: APERTURE.idle },
    ])(t);
    const working = win(t, lists.t0, converge, 0.3, 0.2);
    ap += working * (3.5 * Math.sin(t * 5.2) + (t >= ai.t0 ? 4 * Math.sin(t * 13) : 0));
    st.aperture = ap;
    st.mag = win(t, baseer.t0 + 0.3, lists.t0 + 0.2, 0.25, 0.25);
    st.mic = listen ? win(t, listen.t0 - 0.05, found.t0 + 0.05, 0.2, 0.2) : 0;
    // Tier arcs: one per check, breathing while it runs, full when it is done.
    tiers.forEach((sn, i) => {
      st.arcs[i] = tw(t, sn.t1 - 0.3, 0.42, E.out3);
      if (t >= sn.t0 && t < sn.t1 - 0.3) st.run = i;
    });
    st.breathe = 0.5 + 0.5 * Math.sin(t * 6);
    st.sweepO = 0.9 * win(t, lists.t0, converge, 0.3, 0.2);
    st.sweep = t * 225;
    st.tickRot = t * 3 + 150 * E.in2(seg(t, converge, slam)) + 28 * tw(t, snap, 0.6);
    // Red on the verdict, calm again for the advice.
    const danger = tw(t, slam, 0.05) * (1 - tw(t, todo.t0 + 0.1, 0.7, E.io3));
    st.color = mixc(C.brand, C.danger, danger);
    st.core = tw(t, slam, 0.08) * (1 - tw(t, todo.t0 + 0.1, 0.4));
    st.coreScale = tw(t, slam, 0.5, E.spring);
    st.halo = 0.5 * working + tw(t, slam, 0.1) + 0.4 * smooth(env.voice, t);
    st.glow = 1 + 1.3 * E.bump(seg(t, snap, snap + 0.9), 0.12) + 1.6 * E.bump(seg(t, slam, slam + 1.0), 0.08) + 0.5 * smooth(env.voice, t) + 0.5 * E.in2(seg(t, converge, slam));
    st.scale *= 1 + 0.012 * Math.sin(t * 1.7) + 0.03 * smooth(env.voice, t) * (1 - st.mag) - 0.06 * E.in2(seg(t, converge, slam)) * (1 - tw(t, slam, 0.05));
    // Where the eye looks.
    const look = track([
      { t: snap, d: 0, v: [0, 0] },
      { t: found.t0 + 0.4, d: 0.3, v: [0, 0.9] },
      { t: lists.t0 + 0.4, d: 0.3, v: [0, 0.8] },
      { t: address.t0 + 0.5, d: 0.3, v: [0.2, 0.9] },
      { t: page.t0 + 0.5, d: 0.3, v: [-0.8, 0.7] },
      { t: ai.t0 + 0.5, d: 0.3, v: [0, 0.7] },
      { t: todo.t0 + 0.6, d: 0.4, v: [0, 0.25] },
    ])(t);
    st.gaze = [look[0] + 0.12 * Math.sin(t * 2.3), look[1] + 0.08 * Math.cos(t * 1.9)];
    // A nod on each piece of advice.
    for (const id of ["todo.link", "todo.otp"]) {
      const ln = line(id);
      if (ln) st.y += 12 * L.stage.s * E.bump(seg(t, ln.t0, ln.t0 + 0.5), 0.35);
    }
    st.browLift = 6 * tw(t, snap, 0.4) - 9 * E.bump(seg(t, address.t0 + 1.62, address.t0 + 2.4), 0.2) - 12 * tw(t, slam, 0.2) * (1 - tw(t, todo.t0, 0.5));
    return st;
  }

  async function seek(t) {
    flashes = [];
    const sharp = live.active(t); // a shot of the footage fills the picture: the animation steps aside
    // Camera: a slow drift, a jolt on the verdict.
    const jolt = slam != null ? (1 - seg(t, slam, slam + 0.45)) * (t >= slam ? 1 : 0) : 0;
    cam.dx = 4 * Math.sin(t * 0.45) + 18 * jolt * Math.sin(t * 95);
    cam.dy = 3 * Math.cos(t * 0.37) + 14 * jolt * Math.cos(t * 83);
    stage.style.transform = `translate3d(${(L.stage.x + cam.dx).toFixed(2)}px,${(L.stage.y + cam.dy).toFixed(2)}px,0) scale(${L.stage.s})`;
    world.style.visibility = sharp ? "hidden" : "";

    const h1 = mark("intro.hit1");
    const h2 = mark("intro.hit2");
    const inIntro = intro && t < intro.t1;
    const red = slam != null ? tw(t, slam, 0.06) * mix(1, 0.6, seg(t, slam, slam + 1.1)) * (1 - tw(t, (todo?.t0 ?? 1e9) - 0.1, 0.8, E.io3)) : 0;
    backdrop(t, {
      red,
      warm: todo ? 0.6 * tw(t, todo.t0, 0.9) : 0,
      dim: (converge != null ? 0.7 * E.in2(seg(t, converge, slam)) * (1 - tw(t, slam, 0.05)) : 0) + (inIntro ? 1 - 0.75 * tw(t, h1, 0.3) : 0),
      lift: (inIntro ? 0.5 * E.bump(seg(t, h1, h1 + 1), 0.08) + E.bump(seg(t, h2, h2 + 1.2), 0.08) : 0) + (snap != null ? 0.45 * E.bump(seg(t, snap, snap + 1.2), 0.1) : 0) + 0.25 * smooth(env.voice, t),
      lat: inIntro ? tw(t, h1, 0.5) : 1,
      drift: t * 40,
    });
    await live.update(t);

    fx.clear();
    const st = lensState(t);
    if (!sharp) {
      if (film) {
        message.update(t);
        checks.update(t);
        verdictScene.update(t);
        // Status line: listening, heard, checking.
        const sy = 838;
        put(stListen, { x: 500, y: sy, o: win(t, markIn + 0.15, snap, 0.3, 0.12) });
        put(stHeard, { x: 500, y: sy, o: win(t, snap + 0.05, listen ? listen.t1 - 0.25 : found.t0, 0.15, 0.15) });
        put(stCheck, { x: 500, y: sy, o: listen ? win(t, listen.t1 - 0.2, found.t0 + 0.12, 0.15, 0.15) : 0 });
        // Voice: pulse rings while it listens, the reactive ring while anyone speaks.
        if (st.o > 0.01) {
          const r0 = 204 * st.scale;
          const user = t < snap ? Math.max(smooth(env.live, t), TL.live_audio?.length ? 0 : E.bump(seg(t, say, say + 0.36), 0.3) + 0.9 * E.bump(seg(t, say + 0.4, say + 0.95), 0.25)) : listen && t < found.t0 ? smooth(env.live, t) : 0;
          const hearing = t < snap ? 1 : listen ? win(t, listen.t0, found.t0, 0.1, 0.2) : 0;
          if (hearing > 0) {
            const period = user > 0.15 ? 0.9 : 2.4;
            for (const ph of [0, 0.5]) {
              const p = (t / period + ph) % 1;
              fx.ring(st.x, st.y, r0 * (1.0 + 0.5 * p), t < snap ? C.muted : C.brand, 0.5 * (1 - p) * hearing * st.o, 3);
            }
            const lv = Array.from({ length: 8 }, (_, i) => clamp(user * (0.6 + 0.6 * Math.abs(Math.sin(i * 1.7 + t * 11)))));
            fx.wave(st.x, st.y, r0 * (t < snap ? 1.04 : 1), lv, C.sand, 0.95 * hearing * st.o, 64 * st.scale, t);
          }
          const speaking = smooth(env.voice, t);
          if (t >= snap && speaking > 0.01 && (st.mag ?? 0) < 0.5) {
            const lv = env.bands.map((b) => smooth(b, t));
            fx.wave(st.x, st.y, r0, lv, st.color, 0.95 * st.m, 78 * st.scale, t);
          }
          // The wake: a flare and three rings as the eye opens.
          const wk = seg(t, snap, snap + 0.9);
          if (wk > 0 && wk < 1) {
            fx.streak(st.x, st.y, L.W * 2, 30 * (1 - wk), C.brand, 0.9 * (1 - wk));
            for (const d of [0, 0.1, 0.2]) fx.ring(st.x, st.y, r0 * (0.9 + 2.2 * E.out3(clamp(wk - d))), C.brand, 0.8 * (1 - clamp(wk + d)), 5 - 3 * wk);
            fx.sparks(st.x, st.y, wk, C.brand, 13, 40, r0 * 2.4);
            flashAdd(0.1 * (1 - E.out2(seg(t, snap, snap + 0.18))), "rgb(125 240 220)");
          }
        }
      }
      fullScene.update(t);
      lens.update(st);
    }
    captions.update(t);
    label.update(opts.label === false ? 0 : 1);

    // Cuts into and out of the footage get a two-frame breath of light.
    for (const p of TL.live_pic ?? []) {
      if (p.id === "plate") continue;
      flashAdd(0.22 * (1 - seg(t, p.t0, p.t0 + 0.1)) * (t >= p.t0 ? 1 : 0), "rgb(242 238 230)");
      flashAdd(0.1 * (1 - seg(t, p.t1, p.t1 + 0.12)) * (t >= p.t1 ? 1 : 0), "rgb(125 240 220)");
    }
    void relief;
    void cold;
    void wake;
    void verdict;
    void dir;
    void TAU;
    flashes.sort((a, b) => b[0] - a[0]);
    if (flashes.length) {
      flashEl.style.visibility = "";
      flashEl.style.opacity = clamp(flashes[0][0]).toFixed(3);
      flashEl.style.background = flashes[0][1];
    } else flashEl.style.visibility = "hidden";
  }

  window.__seek = seek;
  await seek(0);
  window.__ready = true;
}

boot().catch((err) => {
  window.__error = String(err?.stack ?? err);
});
