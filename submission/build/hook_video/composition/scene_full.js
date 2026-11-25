// Full-frame scenes: the logo sting that opens the film and the end card that closes it.
import { C, E, clamp, h, mix, put, seg, tw, words } from "./lib.js";

function wordmark(D, size) {
  const en = h("span.en");
  const letters = [...D.wordmarkEn].map((ch) => h("span", { text: ch === " " ? " " : ch }));
  en.append(...letters);
  const bar = h("span.bar", { text: "|" });
  const ar = h("span.ar", { text: D.wordmarkAr });
  const el = h("div.wordmark", { style: `font-size:${size}px` }, en, bar, ar);
  return { el, letters, bar, ar };
}

export function build(ctx) {
  const { full, D, L, TL, sc, fx, flashAdd } = ctx;
  const F = L.full;
  const intro = sc("intro");
  const end = sc("end");
  const m = { hit1: ctx.mark("intro.hit1"), tap1: ctx.mark("intro.tap1"), tap2: ctx.mark("intro.tap2"), hit2: ctx.mark("intro.hit2"), out: ctx.mark("intro.out"), endHit: ctx.mark("end.hit") };
  const alone = TL.variant === "intro";

  // ── Logo sting ─────────────────────────────────────────────────────────────────────────────────
  const wm = wordmark(D, F.introWord);
  const wmAt = h("div.at", {}, h("div.c", {}, wm.el));
  full.append(wmAt);

  // ── End card ───────────────────────────────────────────────────────────────────────────────────
  const ew = wordmark(D, F.endWord);
  const ewAt = h("div.at", {}, h("div.c", {}, ew.el));
  const tag = h("div.end-tag", { dir: "rtl", style: `font-size:${F.endTag}px` });
  const tagWords = words(tag, D.taglineAr);
  tagWords.forEach((w) => w.textContent.includes("الصقر") && w.classList.add("hot"));
  const tagAt = h("div.at", {}, h("div.c", {}, tag));
  const enAt = h("div.at", {}, h("div.c", {}, h("div.end-en", { text: D.taglineEn, style: `font-size:${F.endEn}px` })));
  const siteAt = h("div.at", {}, h("div.c", {}, h("div.end-site", { text: D.site, style: `font-size:${F.endSite}px` })));
  const eventAt = h("div.at", {}, h("div.c", {}, h("div.end-event", { text: D.event, style: `font-size:${F.endEvent}px` })));
  const small = h(
    "div.end-small",
    { style: `font-size:${F.endSmall}px;width:${F.endSmallW}px` },
    h("p", { dir: "rtl", text: D.creditAr }),
    h("p.en", { text: D.creditEn }),
    h("p", { dir: "rtl", text: D.fictionAr + (D.people ? ` ${D.peopleAr}` : "") }),
    h("p.en", { text: D.fictionEn + (D.people ? ` ${D.peopleEn}` : "") }),
  );
  const smallAt = h("div.at", {}, h("div.c", {}, small));
  full.append(ewAt, tagAt, enAt, siteAt, eventAt, smallAt);

  function update(t) {
    // Logo sting: a light crosses the dark and draws the mark; the ring snaps into focus on the first hit; the
    // wordmark lands on the second; then the camera goes through the eye into the story.
    if (intro && t < intro.t1 + 0.3) {
      const cx = F.cx;
      const cy = F.introY;
      const R = 200 * F.introS;
      const sweep = seg(t, 0.22, m.hit1 - 0.1);
      if (sweep > 0 && sweep < 1) {
        const x = mix(-0.25, 1.25, E.io2(sweep)) * L.W;
        fx.streak(x, cy, L.W * 1.1, 18, C.brand, 0.9 * Math.sin(sweep * Math.PI));
        fx.glow(x, cy, R * 1.6, C.brand, 0.2 * Math.sin(sweep * Math.PI));
      }
      const zoom = alone ? 0 : E.in3(seg(t, m.out, intro.t1));
      // First hit: ring, glow and a wide streak.
      const h1 = seg(t, m.hit1, m.hit1 + 0.7);
      if (h1 > 0 && h1 < 1) {
        fx.ring(cx, cy, R * (0.75 + 1.9 * E.out3(h1)), C.brand, 0.9 * (1 - h1), 6 - 4 * h1);
        fx.streak(cx, cy, L.W * 1.9, 26 * (1 - h1), C.brand, 0.95 * (1 - h1));
        fx.sparks(cx, cy, h1, C.brand, 5, 34, R * 2.6);
      }
      for (const tp of [m.tap1, m.tap2]) {
        const p = seg(t, tp, tp + 0.4);
        if (p > 0 && p < 1) fx.ring(cx, cy, R * (0.85 + 0.6 * E.out3(p)), C.sand, 0.6 * (1 - p), 3);
      }
      // Second hit: the wordmark.
      const wy = F.introWordY;
      const h2 = seg(t, m.hit2, m.hit2 + 0.9);
      if (h2 > 0 && h2 < 1) {
        fx.streak(cx, wy, L.W * 2.4, 34 * (1 - h2), C.sand, 0.9 * (1 - h2));
        fx.ring(cx, cy, R * (0.9 + 2.6 * E.out3(h2)), C.brand, 0.7 * (1 - h2), 5 - 3 * h2);
        fx.sparks(cx, wy, h2, C.sand, 9, 54, L.W * 0.75);
        flashAdd(0.3 * (1 - E.out2(seg(t, m.hit2, m.hit2 + 0.16))), "rgb(242 238 230)");
      }
      const land = tw(t, m.hit2, 0.5, E.outE);
      const drift = 1 + 0.03 * seg(t, m.hit2, intro.t1);
      const fade = alone ? 1 - E.in2(seg(t, intro.t1 - 0.4, intro.t1 - 0.04)) : 1;
      put(wmAt, { x: cx, y: wy + 60 * zoom * 6, sx: mix(1.22, 1, land) * drift * (1 + 5 * zoom), o: tw(t, m.hit2, 0.06) * (1 - seg(zoom, 0, 0.5)) * fade, blur: 14 * (1 - tw(t, m.hit2, 0.22)) + 20 * zoom });
      const n = wm.letters.length;
      wm.letters.forEach((el, i) => {
        const p = tw(t, m.hit2 + 0.02 * i, 0.5, E.outE);
        el.style.transform = `translateX(${((i - n) * 16 * (1 - p)).toFixed(2)}px)`;
        el.style.opacity = tw(t, m.hit2 + 0.02 * i, 0.2).toFixed(3);
      });
      wm.ar.style.transform = `translateX(${(70 * (1 - land)).toFixed(2)}px)`;
      wm.bar.style.transform = `scaleY(${tw(t, m.hit2 + 0.08, 0.35, E.spring).toFixed(3)})`;
      if (!alone) flashAdd(0.88 * (E.in2(seg(t, intro.t1 - 0.1, intro.t1)) * (t < intro.t1 ? 1 : 0) + (1 - E.out3(seg(t, intro.t1, intro.t1 + 0.24))) * (t >= intro.t1 ? 1 : 0)), "rgb(226 250 245)");
      else flashAdd(E.in2(seg(t, intro.t1 - 0.4, intro.t1 - 0.04)), "rgb(0 0 0)");
    } else put(wmAt, { o: 0 });

    // End card.
    if (end && t >= end.t0 - 0.05) {
      const hit = m.endHit;
      const hp = seg(t, hit, hit + 0.9);
      if (hp > 0 && hp < 1) {
        fx.streak(F.cx, F.endWordY, L.W * 2.2, 26 * (1 - hp), C.brand, 0.8 * (1 - hp));
        fx.ring(F.cx, F.endY, 200 * F.endS * (0.9 + 1.8 * E.out3(hp)), C.brand, 0.7 * (1 - hp), 4);
      }
      // One slow scan across the lens.
      const sw = seg(t, hit + 0.5, hit + 2.3);
      if (sw > 0 && sw < 1) fx.streak(mix(F.cx - 260 * F.endS * 1.6, F.cx + 260 * F.endS * 1.6, E.io2(sw)), F.endY, 150 * F.endS, 520 * F.endS, C.brand, 0.3 * Math.sin(sw * Math.PI));
      const wp = tw(t, hit, 0.5, E.spring);
      put(ewAt, { x: F.cx, y: F.endWordY, sx: mix(0.8, 1, wp), o: tw(t, hit, 0.12) });
      put(tagAt, { x: F.cx, y: F.endTagY, o: t >= hit ? 1 : 0 });
      tagWords.forEach((w, i) => {
        const t0 = hit + 0.14 + i * 0.09;
        const p = tw(t, t0, 0.5, E.outE);
        w.style.opacity = tw(t, t0, 0.18).toFixed(3);
        w.style.transform = `translateY(${((1 - p) * 44).toFixed(2)}px) scale(${mix(1.12, 1, p).toFixed(4)})`;
        w.style.filter = p < 0.98 ? `blur(${((1 - p) * 9).toFixed(2)}px)` : "";
      });
      put(enAt, { x: F.cx, y: F.endEnY + 12 * (1 - tw(t, hit + 0.62, 0.4)), o: tw(t, hit + 0.62, 0.4, E.out2) });
      put(siteAt, { x: F.endSiteX ?? F.cx, y: F.endSiteY + 12 * (1 - tw(t, hit + 0.78, 0.4)), o: tw(t, hit + 0.78, 0.4, E.out2) });
      put(eventAt, { x: F.endEventX ?? F.cx, y: F.endEventY + 12 * (1 - tw(t, hit + 0.9, 0.4)), o: tw(t, hit + 0.9, 0.4, E.out2) });
      put(smallAt, { x: F.cx, y: F.endSmallY, o: tw(t, hit + 1.0, 0.5, E.out2) });
    } else for (const el of [ewAt, tagAt, enAt, siteAt, eventAt, smallAt]) put(el, { o: 0 });
    void clamp;
  }
  return { update };
}
