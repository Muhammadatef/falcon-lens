// The message: it lands, the finger nearly taps the link, the message is copied instead, and the Falcon finds
// it on the clipboard and reads it through the lens.
import { C, E, clamp, h, icon, mix, put, seg, tw, win } from "./lib.js";

export const CARD = { cold: [500, 470], coldScale: 1.0, found: [500, 668], foundScale: 0.84, chip: [215, 84] };

function smsCard(D) {
  const body = h("p.sms-body", { dir: "rtl" });
  const parts = {};
  D.sms.forEach(([kind, text], i) => {
    if (i) body.append(" ");
    const span = h(`span.k.k-${kind}`, { text });
    body.append(span);
    (parts[kind] ??= []).push(span);
  });
  const ring = h("div.sms-ring");
  const sheen = h("div.sheen");
  const card = h(
    "div.sms.glass",
    {},
    h("div.sms-head", {}, h("span.sms-avatar", { text: "F" }), h("div.sms-meta", {}, h("b", { text: D.sender }), h("small", { text: "رسالة نصية" })), h("span.sms-now", { text: "الآن" })),
    body,
    h("div.sms-foot", { text: D.fixtureNote }),
    sheen,
    ring,
  );
  return { card, parts, ring, sheen };
}

/** Paints the highlight behind a phrase; `p` is 0..1. */
function light(spans, p, color) {
  for (const sp of spans) {
    sp.style.backgroundSize = `${(clamp(p) * 100).toFixed(1)}% 100%`;
    sp.style.color = p > 0.5 && color ? color : "";
  }
}

export function build(ctx) {
  const { stage, TL, D, mark, sc, lensPos, lens, L } = ctx;
  const cs = L.portrait ? 1.12 : 1.0; // the message is larger in the tall frame
  const COLD = L.portrait ? [500, 500] : CARD.cold;
  const { card, parts, ring, sheen } = smsCard(D);
  const anchor = h("div.at", {}, h("div.c", {}, card));
  const finger = h("div.at", {}, h("div.c", {}, h("div.finger")));
  const press = h("div.at", {}, h("div.c", {}, h("div.finger-ring")));
  const stop = h("div.at", {}, h("div.c", {}, h("div.finger-stop")));
  const toast = h("div.at", {}, h("div.c", {}, h("div.toast", {}, icon("copy", 34), h("span", { text: "تم نسخ الرسالة" }), h("small", { text: "Copied" }))));
  const clip = h("div.at", {}, h("div.c", {}, h("div.clip", {}, icon("message", 30), h("span", { text: "الحافظة: رسالة واحدة" }))));
  const ret = h("div.at", {}, h("div.c", {}, h("div.ret", {}, h("i"), h("i"), h("i"), h("i"))));
  const count = h("div.at", {}, h("div.c", {}, h("div.count.mono", { text: "1" })));
  const plate = h("div.at", {}, h("div.c", {}, h("div.plate", {}, h("b", { text: "بصير" }), h("span", { text: "Baseer · the Investigator" }))));
  stage.append(anchor, press, stop, finger, toast, clip, ret, count, plate);

  // The same card again, inside the lens glass, for the magnifier.
  const twin = smsCard(D);
  lens.magInner.append(twin.card);

  // Layout facts, measured once.
  const cw = card.offsetWidth;
  const ch = card.offsetHeight;
  const link = parts.link[0];
  const linkAt = [link.offsetLeft + link.offsetWidth / 2 - cw / 2, link.offsetTop + link.offsetHeight / 2 - ch / 2];
  const urgent = parts.urgent[0];
  const urgentAt = [urgent.offsetLeft + urgent.offsetWidth / 2 - cw / 2, urgent.offsetTop + urgent.offsetHeight / 2 - ch / 2];
  const retBox = ret.querySelector(".ret");
  retBox.style.width = `${cw * CARD.foundScale + 44}px`;
  retBox.style.height = `${ch * CARD.foundScale + 44}px`;

  const cold = sc("cold");
  const found = sc("found");
  const baseer = sc("baseer");
  const lists = sc("lists");
  const m = {
    land: mark("cold.land"), buzz: mark("cold.buzz"), urgent: mark("cold.urgent"), finger: mark("cold.finger"), stop: mark("cold.stop"),
    press: mark("copy.press"), copied: mark("copy.done"), markIn: mark("mark.in"),
  }; // prettier-ignore
  const linkStage = [COLD[0] + linkAt[0] * cs, COLD[1] + linkAt[1] * cs];
  const fingerRest = [linkStage[0] + 26, linkStage[1] + 62]; // the tip hovers just below the link

  /** Where the card is, for the lens and for other scenes: {x, y, s, o, w, h, link: [x, y]}. */
  function cardAt(t) {
    if (!cold || t < m.land - 0.02) return { x: 0, y: 0, s: 1, o: 0, w: cw, h: ch, link: [0, 0] };
    let x = COLD[0];
    let y = COLD[1];
    let s = 1;
    let o = 1;
    let rx = 0;
    let blur = 0;
    // Slam in.
    const a = tw(t, m.land, 0.5, E.outE);
    s = mix(1.42, 1, a) * cs;
    o = tw(t, m.land, 0.16, E.out2);
    rx = mix(16, 0, a);
    blur = mix(16, 0, tw(t, m.land, 0.3, E.out2));
    // Shake with the second buzz.
    const bz = E.bump(seg(t, m.buzz + 0.34, m.buzz + 0.62), 0.2);
    x += Math.sin(t * 150) * 5 * bz;
    y += Math.cos(t * 131) * 2.5 * bz;
    // Into the clipboard chip once it is copied.
    const fold = tw(t, m.markIn - 0.1, 0.42, E.io3);
    if (fold > 0) {
      x = mix(x, CARD.chip[0], fold);
      y = mix(y, CARD.chip[1], fold);
      s = mix(s, 0.14, fold);
      o *= 1 - E.in2(seg(fold, 0.55, 1));
    }
    // Out of the clipboard when the Falcon finds it.
    if (found && t >= found.t0 - 0.02) {
      const u = tw(t, found.t0, 0.55, E.outE);
      x = mix(CARD.chip[0], CARD.found[0], u);
      y = mix(CARD.chip[1], CARD.found[1], u);
      s = mix(0.14, CARD.foundScale, u);
      o = tw(t, found.t0, 0.2, E.out2);
      rx = mix(22, 0, u);
      blur = 0;
      if (lists) {
        const away = tw(t, lists.t0 - 0.05, 0.42, E.io3);
        y += 46 * away;
        s *= 1 - 0.06 * away;
        o *= 1 - away;
        blur = 8 * away;
      }
    }
    return { x, y, s, o, rx, blur, w: cw, h: ch, link: [x + linkAt[0] * s, y + linkAt[1] * s] };
  }

  function update(t) {
    const k = cardAt(t);
    put(anchor, { x: k.x, y: k.y, sx: k.s, o: k.o, rx: k.rx ?? 0, blur: k.blur ?? 0 });
    if (k.o <= 0.002 && (!found || t < found.t0 - 0.1)) {
      for (const el of [finger, press, stop, toast, ret, count, plate]) put(el, { o: 0 });
      put(clip, { o: cold && t >= m.markIn ? win(t, m.markIn + 0.12, (found?.t0 ?? 1e9) + 0.12, 0.3, 0.2) : 0, x: CARD.chip[0], y: CARD.chip[1] });
      if (t < (cold?.t0 ?? 0)) return;
    }
    // A light sweeps the glass as it lands.
    const sh = seg(t, m.land + 0.1, m.land + 1.0);
    sheen.style.transform = `translateX(${mix(-60, 260, E.io2(sh)).toFixed(1)}%) skewX(-12deg)`;
    sheen.style.opacity = (sh > 0 && sh < 1 ? 1 : 0).toFixed(2);

    // Phrases light up: the threat, the code it asks for, the link.
    light(parts.urgent, tw(t, m.urgent, 0.45, E.out3), "#ffd0d2");
    light(parts.otp, tw(t, m.urgent + 0.85, 0.4, E.out3));
    const linkPulse = tw(t, m.finger - 0.15, 0.4, E.out3);
    light(parts.link, linkPulse);
    // Later, in the lens: the brand and the link lock.
    if (baseer) {
      const lock = tw(t, baseer.t1 - 0.4, 0.3, E.out3);
      if (lock > 0) light(parts.brand, lock);
    }

    // The finger: toward the link, frozen, then a long press on the message itself.
    const fin = tw(t, m.finger, m.stop - m.finger, E.out3);
    let fx = mix(170, fingerRest[0], fin);
    let fy = mix(1060, fingerRest[1], fin);
    let fo = tw(t, m.finger, 0.25, E.out2);
    const tremble = (1 - seg(t, m.stop, m.stop + 0.5)) * seg(t, m.stop - 0.5, m.stop);
    fx += Math.sin(t * 38) * 2.5 * tremble;
    fy -= 10 * E.bump(seg(t, m.stop, m.stop + 0.45), 0.25); // it pulls back
    const go = tw(t, m.press, 0.3, E.io3);
    fx = mix(fx, COLD[0] + 40, go);
    fy = mix(fy, COLD[1] + 20, go);
    const pressed = seg(t, m.press + 0.3, m.copied);
    const fs = 1 - 0.1 * E.out2(pressed) + 0.1 * tw(t, m.copied, 0.2);
    fo *= 1 - tw(t, m.copied + 0.05, 0.25, E.in2);
    put(finger, { x: fx, y: fy, sx: fs, o: fo });
    // Stop: two red rings where it nearly tapped.
    const st1 = seg(t, m.stop, m.stop + 0.55);
    const st2 = seg(t, m.stop + 0.14, m.stop + 0.7);
    const ringAt = st1 > 0 && st1 < 1 ? st1 : st2 > 0 && st2 < 1 ? st2 : 0;
    put(stop, { x: fingerRest[0], y: fingerRest[1], sx: mix(0.5, 1.5, E.out3(ringAt)), o: ringAt > 0 ? (1 - ringAt) * (1 - tw(t, m.press, 0.1)) : 0 });
    // Long press: a teal ring fills, then the copied toast.
    put(press, { x: COLD[0] + 40, y: COLD[1] + 20, sx: mix(1.5, 0.75, E.out2(pressed)), o: pressed > 0 && t < m.copied + 0.2 ? clamp(pressed * 2) * (1 - tw(t, m.copied, 0.2)) : 0 });
    ring.style.opacity = E.bump(seg(t, m.copied - 0.05, m.copied + 0.5), 0.2).toFixed(3);
    const tp = tw(t, m.copied, 0.4, E.spring);
    put(toast, { x: COLD[0], y: COLD[1] - (ch * cs) / 2 - 62 + 20 * (1 - tw(t, m.copied, 0.3)), sx: mix(0.6, 1, tp), o: win(t, m.copied, m.markIn + 0.25, 0.12, 0.22) });
    // The clipboard chip the card folds into.
    put(clip, { x: CARD.chip[0], y: CARD.chip[1], sx: mix(0.7, 1, tw(t, m.markIn + 0.12, 0.4, E.spring)), o: win(t, m.markIn + 0.12, (found?.t0 ?? 1e9) + 0.14, 0.2, 0.2) });

    // Found: the reticle locks, the count pops.
    if (found) {
      const lk = tw(t, found.t0 + 0.32, 0.3, E.outE);
      const flash = E.bump(seg(t, found.t0 + 0.32, found.t0 + 0.8), 0.15);
      put(ret, { x: CARD.found[0], y: CARD.found[1], sx: mix(1.22, 1, lk), o: lk * (0.55 + 0.45 * flash) * (1 - tw(t, (baseer?.t0 ?? found.t1) + 0.1, 0.3)) });
      const cp = tw(t, found.t0 + 0.42, 0.45, E.spring);
      put(count, { x: CARD.found[0] - (cw * CARD.foundScale) / 2 + 6, y: CARD.found[1] - (ch * CARD.foundScale) / 2 + 6, sx: cp, o: cp > 0.01 ? 1 - tw(t, (lists?.t0 ?? 1e9) - 0.05, 0.3) : 0 });
    }
    // Baseer: his name, and the card seen through the lens glass.
    if (baseer) {
      const pl = win(t, baseer.t0 + 0.05, baseer.t1 - 0.1, 0.35, 0.25);
      put(plate, { x: 500, y: 176 + 14 * (1 - tw(t, baseer.t0 + 0.05, 0.4)), o: pl });
      const lp = lensPos(t);
      const M = 1.55; // magnification
      const f = M / lp.s;
      twin.card.style.transform = `translate(${(141 + (k.x - lp.x - (cw / 2) * k.s) * f).toFixed(2)}px,${(141 + (k.y - lp.y - (ch / 2) * k.s) * f).toFixed(2)}px) scale(${(k.s * f).toFixed(4)})`;
      twin.card.style.transformOrigin = "0 0";
      light(twin.parts.urgent, 1, "#ffd0d2");
      light(twin.parts.otp, 1);
      light(twin.parts.link, 1);
      light(twin.parts.brand, tw(t, baseer.t1 - 0.4, 0.3, E.out3));
    }
  }
  return { update, cardAt, linkStage, urgentStage: [COLD[0] + urgentAt[0] * cs, COLD[1] + urgentAt[1] * cs], size: [cw, ch], linkAt };
}
