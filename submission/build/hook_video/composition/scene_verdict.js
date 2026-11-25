// The verdict «خطِر» on the earcon, the hand-over to Dir (the Sentinel) who links the reports into one campaign,
// and what to do now.
import { C, E, TAU, h, icon, mix, mixc, put, rgb, s, seg, tw, win } from "./lib.js";

export const WORD = { x: 500, y: 690 };
const RADAR = { x: 560, y: 590, r: 310 };
const NODES = [[455, 580], [735, 468], [652, 762]]; // prettier-ignore

export function build(ctx) {
  const { stage, D, sc, line, lensPos, P, fx, L, flashAdd } = ctx;
  const verdict = sc("verdict");
  const dir = sc("dir");
  const todo = sc("todo");
  const end = sc("end");
  const slam = ctx.mark("verdict.slam");
  const m = { ping1: ctx.mark("dir.ping1"), ping2: ctx.mark("dir.ping2"), link: ctx.mark("dir.link") };

  // ── Verdict ────────────────────────────────────────────────────────────────────────────────────
  const word = h("div.verdict-word", { text: "خطِر" });
  const ghostR = h("div.verdict-ghost", { text: "خطِر", style: "color:#ff2b3a" });
  const ghostC = h("div.verdict-ghost", { text: "خطِر", style: "color:#35e6ff" });
  const shine = h("div.verdict-ghost", { text: "خطِر", style: "color:#fff;transform:translateX(-50%);mask-image:linear-gradient(100deg,transparent 42%,#000 50%,transparent 58%);mask-size:300% 100%;-webkit-mask-image:linear-gradient(100deg,transparent 42%,#000 50%,transparent 58%);-webkit-mask-size:300% 100%" });
  const wordWrap = h("div", { style: "position:relative" }, word, ghostR, ghostC, shine);
  const sub = h("div.verdict-sub", {}, h("span.verdict-kind", { text: "رسالة" }), h("span.verdict-en", { text: "DANGEROUS" }));
  const wordAt = h("div.at", {}, h("div.c", {}, h("div.verdict", {}, wordWrap)));
  const subAt = h("div.at", {}, h("div.c", {}, sub));
  const arbiter = h("div.at", {}, h("div.c", {}, h("div.arbiter", {}, h("b", { text: D.arbiterAr }), h("small", { text: D.arbiterEn }))));
  const token = h("div.at", {}, h("div.c", {}, h("div.token", {}, icon("dangerous", 40), h("span", { text: "خطِر" }))));
  stage.append(wordAt, subAt, arbiter, token);

  // ── Dir ────────────────────────────────────────────────────────────────────────────────────────
  const radarSvg = s("svg", { viewBox: "0 0 620 620" });
  for (const [r, w, o] of [[306, 3, 0.75], [214, 1.5, 0.4], [122, 1.5, 0.4], [30, 1.5, 0.4]]) radarSvg.append(s("circle", { cx: 310, cy: 310, r, "stroke-width": w, opacity: o })); // prettier-ignore
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    const r0 = i % 6 ? 296 : 288;
    radarSvg.append(s("line", { x1: 310 + Math.cos(a) * r0, y1: 310 + Math.sin(a) * r0, x2: 310 + Math.cos(a) * 304, y2: 310 + Math.sin(a) * 304, "stroke-width": 1.5, opacity: 0.5 }));
  }
  radarSvg.append(s("line", { x1: 4, y1: 310, x2: 616, y2: 310, "stroke-width": 1, opacity: 0.2 }), s("line", { x1: 310, y1: 4, x2: 310, y2: 616, "stroke-width": 1, opacity: 0.2 }));
  const sweep = h("div.radar-sweep");
  const radar = h("div.at", {}, h("div.c", {}, h("div.radar", {}, h("div.radar-disc"), sweep, radarSvg)));
  const dirPlate = h("div.at", {}, h("div.c", {}, h("div.plate", {}, h("b", { text: "درع" }), h("span", { text: "Dir' · the Sentinel" }))));
  const nodes = NODES.map((_, i) => {
    const box = h("div.node", {}, icon("message", 38));
    const label = h("div.node-label", { text: i ? "بلاغ مشابه" : "رسالتك" });
    const a = h("div.at", {}, h("div.c", {}, box));
    const la = h("div.at", {}, h("div.c", {}, label));
    return { a, la, box };
  });
  const campaign = h("div.at", {}, h("div.c", {}, h("div.campaign", {}, h("b", { text: "حملة نصب واحدة" }), h("small", { text: "one scam campaign" }))));
  stage.append(radar, dirPlate, ...nodes.flatMap((n) => [n.a, n.la]), campaign);

  // ── What to do now ─────────────────────────────────────────────────────────────────────────────
  const rows = [
    ["url", "لا تضغط على الرابط", "Don't tap the link", "todo.link"],
    ["key", "لا تعطي حد الرمز", "Never share the code", "todo.otp"],
  ].map(([ic, ar, en, id]) => {
    const no = s("svg", { class: "no", viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": 2.6, "stroke-linecap": "round" }, s("path", { d: "M4.5 4.5l15 15", pathLength: 1, "stroke-dasharray": 1 }));
    const el = h("div.todo-row", {}, h("div.todo-ico", {}, icon(ic, 42), no), h("div", {}, h("b", { text: ar }), h("small", { text: en })));
    return { el, no: no.firstChild, t: line(id)?.t0 };
  });
  const card = h("div.todo.glass", {}, h("h3", {}, h("span", { text: "ما عليك فعله الآن" }), h("small", { text: "What to do now" })), ...rows.map((r) => r.el), h("div.sheen"));
  const cardAt = h("div.at", {}, h("div.c", {}, card));
  stage.append(cardAt);
  const sheen = card.querySelector(".sheen");

  function update(t) {
    const lp = lensPos(t);
    const lf = P(lp.x, lp.y);
    const S = L.stage.s;
    let tok = { o: 0 }; // the small red verdict token: flies to the radar, later sits above the advice

    if (verdict && slam != null) {
      const b = dir?.t0 ?? verdict.t1;
      const on = t >= slam - 0.02 && t < b + 0.6;
      if (!on) for (const el of [wordAt, subAt, arbiter]) put(el, { o: 0 });
      else {
        // The word lands on the earcon: big, then settles; red and cyan ghosts close in; a light crosses it.
        const hit = tw(t, slam, 0.34, E.outE);
        const gone = tw(t, b - 0.05, 0.4, E.io3);
        const sc0 = mix(2.3, 1, hit) * (1 + 0.012 * Math.sin((t - slam) * 3)) * (1 - 0.8 * gone);
        put(wordAt, { x: mix(WORD.x, NODES[0][0], gone), y: mix(WORD.y, NODES[0][1], gone), sx: sc0, o: tw(t, slam, 0.05) * (1 - E.in2(seg(gone, 0.5, 1))) });
        const split = (1 - tw(t, slam, 0.3, E.out3)) * 26;
        ghostR.style.transform = `translateX(calc(-50% - ${split.toFixed(2)}px))`;
        ghostC.style.transform = `translateX(calc(-50% + ${split.toFixed(2)}px))`;
        ghostR.style.opacity = ghostC.style.opacity = (split > 0.3 ? 0.75 : 0).toFixed(2);
        const sh = seg(t, slam + 0.38, slam + 1.05);
        shine.style.opacity = sh > 0 && sh < 1 ? "0.85" : "0";
        const pos = `${mix(110, -10, sh).toFixed(1)}% 0`;
        shine.style.maskPosition = pos;
        shine.style.webkitMaskPosition = pos;
        const sp = tw(t, slam + 0.34, 0.4, E.spring);
        put(subAt, { x: WORD.x, y: WORD.y + 196, sx: mix(0.8, 1, sp), o: win(t, slam + 0.34, b, 0.15, 0.25) });
        put(arbiter, { x: 500, y: 962, o: win(t, slam + 0.95, b - 0.05, 0.4, 0.25) });
        // Shock rings and sparks from the lens.
        for (const d of [0, 0.12]) {
          const p = seg(t, slam + d, slam + d + 0.85);
          fx.ring(lf[0], lf[1], (lp.s * 190 + 1500 * E.out3(p)) * S, C.danger, (1 - p) * (d ? 0.5 : 0.9), (10 - 7 * p) * S);
        }
        fx.sparks(lf[0], lf[1], seg(t, slam, slam + 0.9), C.danger, 77, 60, 760 * S);
        fx.streak(lf[0], lf[1], L.W * 2.2, 46 * S * (1 - seg(t, slam, slam + 0.5)), C.danger, 0.9 * (1 - seg(t, slam, slam + 0.5)));
      }
      const fl = seg(t, slam, slam + 0.26);
      if (fl > 0 && fl < 1) flashAdd(0.62 * (1 - E.out2(fl)), `radial-gradient(circle at ${lf[0].toFixed(0)}px ${lf[1].toFixed(0)}px, rgb(255 244 240), rgb(255 80 92) 30%, rgb(212 42 56 / 0.35) 62%, rgb(43 15 21 / 0) 100%)`);
    }

    if (dir) {
      const a = dir.t0;
      const b = todo?.t0 ?? dir.t1;
      const on = t >= a - 0.1 && t < b + 0.45;
      if (!on) for (const el of [radar, dirPlate, campaign, ...nodes.flatMap((n) => [n.a, n.la])]) put(el, { o: 0 });
      else {
        const out = tw(t, b - 0.02, 0.36, E.in2);
        const rin = tw(t, a + 0.08, 0.7, E.outE);
        put(radar, { x: RADAR.x, y: RADAR.y + 30 * out, sx: mix(0.7, 1, rin), o: tw(t, a + 0.08, 0.35) * (1 - out) });
        sweep.style.transform = `rotate(${((t - a) * 150).toFixed(2)}deg)`;
        put(dirPlate, { x: 812, y: 226 + 14 * (1 - tw(t, a + 0.3, 0.4)), o: win(t, a + 0.3, b, 0.35, 0.25) });
        // The verdict travels to the radar as a token and becomes the first node.
        const fly = tw(t, a + 0.1, 0.75, E.io3);
        const tx = mix(WORD.x, NODES[0][0], fly);
        const ty = mix(WORD.y, NODES[0][1], fly) - 120 * Math.sin(fly * Math.PI);
        tok = { x: tx, y: ty, sx: mix(1.1, 0.5, fly), o: tw(t, a + 0.1, 0.2) * (1 - tw(t, a + 0.8, 0.15)) };
        const times = [a + 0.82, m.ping1, m.ping2];
        const linked = tw(t, m.link, 0.55, E.out3);
        nodes.forEach((n, i) => {
          const p = tw(t, times[i], 0.5, E.spring);
          const hot = i === 0 ? 1 : tw(t, m.link + 0.15 * i, 0.3);
          n.box.className = hot > 0.5 ? "node node--hot" : "node";
          put(n.a, { x: NODES[i][0], y: NODES[i][1] + 30 * out, sx: p, o: p > 0.01 ? 1 - out : 0 });
          put(n.la, { x: NODES[i][0], y: NODES[i][1] + 66 + 30 * out, o: win(t, times[i] + 0.15, b, 0.25, 0.25) });
          const rp = seg(t, times[i], times[i] + 0.9);
          const at = P(NODES[i][0], NODES[i][1]);
          fx.ring(at[0], at[1], (40 + 150 * E.out3(rp)) * S, i ? C.sand : C.danger, 0.8 * (1 - rp), 3 * S);
        });
        // Dir links them: three threads, then one ring around the campaign.
        const pairs = [[0, 1], [1, 2], [2, 0]]; // prettier-ignore
        pairs.forEach(([i, j], k) => {
          const p = tw(t, m.link + k * 0.1, 0.45, E.io3) * (1 - out);
          const A = P(...NODES[i]);
          const B = P(...NODES[j]);
          fx.line(A[0], A[1], B[0], B[1], mixc(C.sand, C.danger, linked), 0.85 * (1 - out), 4 * S, p);
          if (p > 0 && p < 1) fx.glow(mix(A[0], B[0], p), mix(A[1], B[1], p), 22 * S, C.text, 0.8);
        });
        const cx = (NODES[0][0] + NODES[1][0] + NODES[2][0]) / 3;
        const cy = (NODES[0][1] + NODES[1][1] + NODES[2][1]) / 3;
        const hull = tw(t, m.link + 0.3, 0.6, E.outE);
        if (hull > 0) {
          const c = P(cx, cy);
          const g = fx.g;
          g.save();
          g.globalCompositeOperation = "lighter";
          g.setLineDash([14 * S, 12 * S]);
          g.lineDashOffset = -t * 40;
          g.strokeStyle = rgb(C.danger, 0.8 * hull * (1 - out));
          g.lineWidth = 3.5 * S;
          g.beginPath();
          g.arc(c[0], c[1], mix(300, 228, hull) * S, 0, TAU);
          g.stroke();
          g.restore();
        }
        const cp = tw(t, m.link + 0.45, 0.5, E.spring);
        put(campaign, { x: RADAR.x, y: 928 + 30 * out, sx: mix(0.7, 1, cp), o: win(t, m.link + 0.45, b, 0.15, 0.25) });
        // The hand-over itself: a thread of light from the lens to the radar.
        const hp = seg(t, a + 0.05, a + 0.7);
        if (hp > 0 && t < a + 1.3) fx.curve(lf, P(NODES[0][0], NODES[0][1]), -0.18, C.sand, 0.55 * (1 - seg(t, a + 0.9, a + 1.3)), 3 * S, E.io2(hp));
      }
    }

    if (todo) {
      const a = todo.t0;
      const b = end?.t0 ?? todo.t1;
      const on = t >= a - 0.1 && t < b + 0.4;
      if (!on) put(cardAt, { o: 0 });
      else {
        const out = tw(t, b - 0.05, 0.32, E.in2);
        const inn = tw(t, a + 0.02, 0.6, E.outE);
        put(cardAt, { x: 500, y: 660 + 70 * (1 - inn) + 50 * out, sx: mix(0.98, 1.08, inn), o: tw(t, a + 0.02, 0.3) * (1 - out), rx: mix(10, 0, inn) });
        const sh = seg(t, a + 0.25, a + 1.25);
        sheen.style.transform = `translateX(${mix(-60, 260, E.io2(sh)).toFixed(1)}%) skewX(-12deg)`;
        sheen.style.opacity = sh > 0 && sh < 1 ? "1" : "0";
        rows.forEach((r, i) => {
          const t0 = (r.t ?? a + 1 + i) - 0.06;
          const p = tw(t, t0, 0.5, E.outE);
          r.el.style.opacity = mix(0.22, 1, tw(t, t0, 0.25)).toFixed(3);
          r.el.style.transform = `translateX(${((1 - p) * 60).toFixed(2)}px)`;
          r.el.style.borderColor = rgb(mixc(C.border, C.brand, E.bump(seg(t, t0, t0 + 1.4), 0.2)));
          r.no.setAttribute("stroke-dashoffset", (1 - tw(t, t0 + 0.3, 0.35, E.io3)).toFixed(4));
        });
        // The verdict stays in view above the advice.
        if (t >= a + 0.15) tok = { x: 500, y: 372 + 20 * (1 - tw(t, a + 0.15, 0.4)) + 50 * out, sx: 0.8, o: win(t, a + 0.15, b, 0.3, 0.25) };
      }
    }
    put(token, tok);
  }
  return { update };
}
