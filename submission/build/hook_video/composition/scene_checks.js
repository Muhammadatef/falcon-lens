// Baseer's four checks, one per tier of the cascade: known lists (T0), the address (T1), the page in the isolated
// browser (T2), the language model (T3). Each leaves a finding, worded as the product words it, in the evidence tray.
import { C, E, TAU, clamp, h, icon, mix, mixc, put, rgb, rng, s, seg, tw, win } from "./lib.js";

function pill(ar, en, neutral = false) {
  const mark = s("svg", { class: "pill-mark", width: 28, height: 28, viewBox: "0 0 16 16" }, neutral ? s("circle", { cx: 8, cy: 8, r: 4.5, fill: "none", stroke: "currentColor", "stroke-width": 2 }) : s("path", { d: "M8 2.5 14.5 13.5h-13z", fill: "currentColor" }));
  return h("div.at", {}, h("div.c", {}, h(`div.pill${neutral ? ".pill--neutral" : ""}`, {}, mark, h("div", {}, h("b", { text: ar }), h("small", { text: en })))));
}
function chip(label, neutral = false) {
  const mark = s("svg", { width: 15, height: 15, viewBox: "0 0 16 16" }, neutral ? s("circle", { cx: 8, cy: 8, r: 4.5, fill: "none", stroke: "currentColor", "stroke-width": 2.4 }) : s("path", { d: "M8 2.5 14.5 13.5h-13z", fill: "currentColor" }));
  return h("div.at", {}, h("div.c", {}, h(`div.chipx${neutral ? ".chipx--neutral" : ""}`, {}, mark, h("span", { text: label }))));
}
function chars(text, cls) {
  const row = h(`div.addr${cls ? "." + cls : ""}`);
  const spans = [...text].map((ch) => h("span", { text: ch }));
  row.append(...spans);
  return { row, spans };
}
const hexid = (R, n) => Array.from({ length: n }, () => "0123456789abcdef"[Math.floor(R() * 16)]).join("");

export const ADDR = { y: 600, yOfficial: 712, x0: 41, cw: 30.6, lensY: 272 };

export function build(ctx) {
  const { stage, D, sc, line, lensPos, P, fx, L, message } = ctx;
  const lists = sc("lists");
  const address = sc("address");
  const page = sc("page");
  const ai = sc("ai");
  const verdict = sc("verdict");
  const converge = ctx.mark("verdict.converge");
  const slam = ctx.mark("verdict.slam");

  // ── T0: known lists ────────────────────────────────────────────────────────────────────────────
  const urlchip = h("div.at", {}, h("div.c", {}, h("div.urlchip", { text: D.link })));
  const floor = h("canvas", { width: 1000, height: 560 });
  const floorAt = h("div.at", {}, h("div.floor-clip", {}, h("div.floor-wrap", {}, floor)));
  const listsPill = pill(`المؤشرات المعروفة: ${D.findings.lists[0]}`, D.findings.lists[1], true);
  stage.append(floorAt, urlchip, listsPill);
  const fg = floor.getContext("2d");
  const R = rng(7);
  const cols = [90, 290, 500, 710, 910].map((x, i) => ({
    x,
    speed: 150 + 60 * ((i * 37) % 5),
    rows: Array.from({ length: 30 }, () => (R() < 0.55 ? `hxxp://${hexid(R, 6)}[.]test/${hexid(R, 3)}` : R() < 0.5 ? `sha256:${hexid(R, 9)}…` : `kit:${hexid(R, 7)}`)),
  }));
  function drawFloor(t, a) {
    fg.clearRect(0, 0, 1000, 560);
    if (a <= 0.003) return;
    fg.font = '600 23px "JetBrains Mono Variable"';
    fg.textAlign = "center";
    const scanY = 250;
    for (const c of cols) {
      for (let i = 0; i < c.rows.length; i++) {
        const y = ((i * 44 + t * c.speed) % (c.rows.length * 44)) - 44;
        if (y < -30 || y > 590) continue;
        const depth = clamp(y / 560);
        const near = Math.exp(-Math.pow((y - scanY) / 26, 2));
        const col = mixc(C.faint, C.brandHi, near);
        fg.fillStyle = rgb(col, a * (0.12 + 0.6 * depth + 0.5 * near) * (1 - E.in2(seg(y, 470, 560))));
        fg.fillText(c.rows[i], c.x, y);
      }
    }
    const lin = fg.createLinearGradient(0, scanY - 30, 0, scanY + 6);
    lin.addColorStop(0, rgb(C.brand, 0));
    lin.addColorStop(1, rgb(C.brand, 0.5 * a));
    fg.fillStyle = lin;
    fg.fillRect(0, scanY - 30, 1000, 36);
    fg.fillStyle = rgb(C.brandHi, 0.95 * a);
    fg.fillRect(0, scanY + 4, 1000, 3);
  }

  // ── T1: the address ────────────────────────────────────────────────────────────────────────────
  const fake = chars(D.hostLookalike);
  const real = chars(D.hostOfficial, "addr--official");
  const fakeAt = h("div.at", {}, h("div", { style: "position:absolute;left:0;top:0;transform:translateY(-50%)" }, fake.row));
  const realAt = h("div.at", {}, h("div", { style: "position:absolute;left:0;top:0;transform:translateY(-50%)" }, real.row));
  const realLabel = h("div.at", {}, h("div.c", {}, h("div.addr-label", { html: `النطاق الرسمي المسجَّل لـ<b>«${D.bankAr}»</b>` })));
  const brk = h("div.at", {}, h("div.c", {}, h("div.addr-brk")));
  const tag = h("div.at", {}, h("div.c", {}, h("div.addr-tag", {}, h("span", { text: "كلمة مضافة" }), h("small", { text: "added word" }))));
  const addrPill = pill(D.findings.address[0], D.findings.address[1]);
  stage.append(fakeAt, realAt, realLabel, brk, tag, addrPill);
  const addedFrom = D.hostLookalike.indexOf(D.addedWord);
  const addedTo = addedFrom + D.addedWord.length;
  const addedX = ADDR.x0 + ((addedFrom + addedTo) / 2) * ADDR.cw;

  // ── T2: the isolated browser ───────────────────────────────────────────────────────────────────
  const fields = [["كلمة المرور", "password"], ["رقم البطاقة", "card"], ["رمز التحقق (OTP)", "otp"]].map(([label]) => { // prettier-ignore
    const flag = h("div.field-flag");
    return { el: h("div.field", {}, h("s"), h("label", { text: label }), flag), flag };
  });
  const skel = h("div.page-skel");
  const headFlag = h("div.head-flag");
  const beam = h("div.beam");
  const pageEl = h(
    "div.page",
    {},
    h("div.page-banner", { text: "TEST FIXTURE, not a real site / صفحة اختبار، ليست موقعاً حقيقياً" }),
    h("div.page-head", {}, h("div.page-logo"), h("div", {}, h("b", { text: D.bankEn }), h("span", { text: D.bankAr }))),
    h("div.page-note", { text: "حسابك مقيّد، تحقق الآن للمتابعة." }),
    h("div.page-form", {}, ...fields.map((f) => f.el)),
    h("div.page-btn", { text: "تحقق / Verify" }),
    headFlag,
    skel,
    beam,
  );
  const browser = h("div.browser", {}, h("div.browser-bar", {}, h("u"), h("u"), h("u"), h("div.browser-url", { text: `hxxp://${D.link}` })), pageEl);
  const chamber = h("div.at", {}, h("div.c", {}, h("div.chamber", {}, h("i"), h("i"), h("i"), h("i"), h("div.chamber-tab", { style: "right:auto;left:46px" }, h("b", { text: "متصفح معزول" }), h("span", { text: "SANDBOX" })))));
  const browserAt = h("div.at", {}, h("div.c", {}, browser));
  const brandPill = pill(D.findings.page_brand[0], D.findings.page_brand[1]);
  const formPill = pill(D.findings.page_form[0], D.findings.page_form[1]);
  const nokeys = h("div.at", {}, h("div.c", {}, h("div.nokeys", {}, h("span.ico", {}, icon("keyboard", 44), icon("slash", 44)), h("span", { text: "لا يُكتب فيها شيء" }))));
  stage.append(chamber, browserAt, brandPill, formPill, nokeys);
  const CH = { x: 455, y: 606 };

  // ── T3: the language model ─────────────────────────────────────────────────────────────────────
  const tokBox = h("div.tokens");
  const toks = [];
  D.sms.forEach(([kind, text]) => {
    const list = kind === "link" ? [text] : text.split(/\s+/);
    list.forEach((w) => {
      const el = h(`span.tok${kind === "link" ? ".mono" : ""}`, { text: w });
      tokBox.append(el, " ");
      toks.push({ el, kind });
    });
  });
  const tokAt = h("div.at", {}, h("div.c", {}, tokBox));
  const llm = h("div.at", {}, h("div.c", {}, h("div.llm", {}, h("b", { text: "نموذج الذكاء الاصطناعي اللغوي" }), h("span", { text: "AI language model · reads and explains" }))));
  const aiPill = pill(D.findings.ai[0], D.findings.ai[1]);
  stage.append(tokAt, llm, aiPill);
  const TOK = { x: 500, y: 672 };
  const tw0 = tokBox.offsetWidth;
  const th0 = tokBox.offsetHeight;
  for (const k of toks) k.at = [TOK.x - tw0 / 2 + k.el.offsetLeft + k.el.offsetWidth / 2, TOK.y - th0 / 2 + k.el.offsetTop + k.el.offsetHeight / 2];
  const GROUPS = [["urgent", C.danger, 0.7], ["otp", C.warn, 1.15], ["link", C.nws, 1.6], ["brand", C.sand, 1.6]]; // prettier-ignore

  // ── The evidence tray ──────────────────────────────────────────────────────────────────────────
  const trayDefs = [
    ["القوائم", true, lists ? lists.t1 - 0.35 : 0],
    ["كلمة مضافة", false, address ? address.t1 - 0.4 : 0],
    ["انتحال البنك", false, page ? page.t0 + 2.2 : 0],
    ["بيانات البطاقة", false, page ? page.t0 + 2.95 : 0],
    ["أسلوب النصابين", false, ai ? ai.t1 - 0.5 : 0],
  ];
  const tray = trayDefs.map(([label, neutral, at]) => ({ el: chip(label, neutral), at }));
  stage.append(...tray.map((c) => c.el));
  let edge = 955;
  for (const c of tray) {
    const w = c.el.firstChild.firstChild.offsetWidth;
    c.x = edge - w / 2;
    c.y = 956;
    edge -= w + 12;
  }

  function update(t) {
    const lp = lensPos(t);
    // T0 ─ the link lifts out of the message and is matched against the lists.
    if (lists) {
      const a = lists.t0;
      const b = lists.t1;
      const from = message.cardAt(a).link;
      const up = tw(t, a - 0.05, 0.5, E.outE);
      const gone = address ? tw(t, address.t0 - 0.02, 0.22, E.in2) : 0;
      put(urlchip, { x: mix(from[0], 500, up), y: mix(from[1], 505, up), sx: mix(0.66, 1, up) * (1 + 0.5 * gone), o: tw(t, a - 0.05, 0.15) * (1 - gone) });
      const fa = win(t, a + 0.1, b + 0.2, 0.4, 0.3);
      if (fa > 0.003) {
        floorAt.style.visibility = "";
        floorAt.style.transform = `translate3d(500px,604px,0)`;
        floorAt.style.opacity = fa.toFixed(3);
        drawFloor(t, 1);
      } else floorAt.style.visibility = "hidden";
      const pp = tw(t, b - 0.8, 0.45, E.spring);
      put(listsPill, { x: 500, y: 676 + 16 * (1 - tw(t, b - 0.8, 0.35)), sx: mix(0.8, 1, pp), o: win(t, b - 0.8, b + 0.12, 0.15, 0.2) });
    }

    // T1 ─ the address, letter by letter, against the bank's registered one.
    if (address) {
      const a = address.t0;
      const b = address.t1;
      const out = tw(t, b - 0.02, 0.28, E.in2);
      const tm = a + 1.62; // the mismatch
      const on = t >= a - 0.1 && t < b + 0.35;
      for (const el of [fakeAt, realAt, realLabel, brk, tag, addrPill]) if (!on) put(el, { o: 0 });
      if (on) {
        put(fakeAt, { x: ADDR.x0, y: ADDR.y - 30 * out, o: 1 - out });
        const slide = tw(t, tm + 0.08, 0.45, E.io3);
        put(realAt, { x: ADDR.x0, y: ADDR.yOfficial - 30 * out, o: tw(t, a + 0.78, 0.3) * (1 - out) });
        put(realLabel, { x: ADDR.x0 + (D.hostOfficial.length * ADDR.cw) / 2 + (D.addedWord.length * ADDR.cw * slide) / 2, y: ADDR.yOfficial + 58 - 30 * out, o: tw(t, a + 0.95, 0.35) * (1 - out) });
        fake.spans.forEach((sp, i) => {
          const cx = ADDR.x0 + (i + 0.5) * ADDR.cw;
          const inn = tw(t, a + i * 0.012, 0.3, E.outE);
          const read = Math.exp(-Math.pow((cx - lp.x) / 62, 2)) * win(t, a + 0.2, tm, 0.2, 0.2);
          const pair = i < addedFrom ? E.bump(seg(t, a + 0.98 + i * 0.03, a + 1.36 + i * 0.03), 0.3) : 0;
          const added = i >= addedFrom && i < addedTo;
          const hit = added ? tw(t, tm + (i - addedFrom) * 0.02, 0.3, E.spring) : 0;
          let col = mixc(C.text, C.brandHi, clamp(read + pair));
          if (added) col = mixc(col, C.danger, clamp(hit));
          sp.style.color = rgb(col);
          sp.style.opacity = inn.toFixed(3);
          sp.style.transform = `translateY(${((1 - inn) * 22 - 7 * read - 16 * hit).toFixed(2)}px) scale(${(1 + 0.12 * read).toFixed(3)})`;
          sp.style.textShadow = added && hit > 0.05 ? `0 0 ${(22 * hit).toFixed(0)}px rgb(212 42 56 / 0.8)` : "";
        });
        real.spans.forEach((sp, i) => {
          const inn = tw(t, a + 0.78 + i * 0.012, 0.3, E.outE);
          const pair = i < addedFrom ? E.bump(seg(t, a + 0.98 + i * 0.03, a + 1.36 + i * 0.03), 0.3) : 0;
          const shift = i >= addedFrom ? D.addedWord.length * ADDR.cw * slide : 0;
          sp.style.color = rgb(mixc(C.muted, C.brandHi, pair));
          sp.style.opacity = inn.toFixed(3);
          sp.style.transform = `translate(${shift.toFixed(2)}px,${((1 - inn) * 18).toFixed(2)}px)`;
        });
        const bk = tw(t, tm + 0.02, 0.35, E.spring);
        put(brk, { x: addedX, y: ADDR.y - 62 - 16 * clamp(bk) - 30 * out, sx: bk, o: bk > 0.01 ? 1 - out : 0 });
        put(tag, { x: addedX, y: ADDR.y - 118 - 16 * clamp(bk) - 30 * out, sx: mix(0.7, 1, bk), o: tw(t, tm + 0.1, 0.25) * (1 - out) });
        const pp = tw(t, a + 2.05, 0.45, E.spring);
        put(addrPill, { x: 500, y: 868 + 16 * (1 - tw(t, a + 2.05, 0.35)), sx: mix(0.8, 1, pp), o: win(t, a + 2.05, b + 0.08, 0.15, 0.2) });
      }
    }

    // T2 ─ the page, opened where nothing can leave and nothing is typed.
    if (page) {
      const a = page.t0;
      const b = page.t1;
      const on = t >= a - 0.1 && t < b + 0.4;
      for (const el of [chamber, browserAt, brandPill, formPill, nokeys]) if (!on) put(el, { o: 0 });
      if (on) {
        const out = tw(t, b - 0.02, 0.34, E.in2);
        const cin = tw(t, a - 0.02, 0.6, E.outE);
        put(chamber, { x: CH.x, y: CH.y + 40 * out, sx: mix(0.9, 1, cin) * (1 - 0.05 * out), o: tw(t, a - 0.02, 0.3) * (1 - out), ry: mix(-9, 0, cin) });
        const bin = tw(t, a + 0.18, 0.6, E.outE);
        put(browserAt, { x: CH.x, y: CH.y + 6 + 40 * out, sx: mix(0.86, 1, bin) * (1 - 0.05 * out), o: tw(t, a + 0.18, 0.3) * (1 - out), ry: mix(-9, 0, cin) });
        skel.style.opacity = (1 - tw(t, a + 0.7, 0.35, E.out2)).toFixed(3);
        const sweep = seg(t, a + 1.0, a + 2.55);
        const by = mix(-150, 500, E.io2(sweep));
        beam.style.transform = `translateY(${by.toFixed(1)}px)`;
        beam.style.opacity = sweep > 0 && sweep < 1 ? "1" : "0";
        const line0 = by + 147; // the bright edge of the beam, in page coordinates
        headFlag.style.opacity = tw(t, a + 1.0 + 1.55 * 0.3, 0.25, E.spring).toFixed(3);
        fields.forEach((f, i) => {
          const y = f.el.offsetTop + 22;
          f.flag.style.opacity = (line0 > y && sweep > 0 ? tw(t, a + 1.0 + 1.55 * clamp((y + 150) / 650) * 1.02, 0.22, E.spring) : 0).toFixed(3);
          void i;
        });
        const p1 = tw(t, a + 1.72, 0.45, E.spring);
        put(brandPill, { x: 410, y: 806 + 16 * (1 - tw(t, a + 1.72, 0.35)) + 40 * out, sx: mix(0.8, 1, p1), o: win(t, a + 1.72, b + 0.05, 0.15, 0.25) });
        const p2 = tw(t, a + 2.45, 0.45, E.spring);
        put(formPill, { x: 530, y: 893 + 16 * (1 - tw(t, a + 2.45, 0.35)) + 40 * out, sx: mix(0.8, 1, p2), o: win(t, a + 2.45, b + 0.05, 0.15, 0.25) });
        const said = line("investigator.page")?.words.find((w) => w[0].startsWith("وما"))?.[1] ?? a + 2.7;
        const nk = tw(t, said, 0.45, E.spring);
        put(nokeys, { x: 540, y: 226 + 40 * out, sx: mix(0.7, 1, nk), o: win(t, said, b + 0.05, 0.12, 0.25) });
        // The lens looks in: a soft cone of light from it to the line being read.
        if (sweep > 0 && sweep < 1) {
          const lf = P(lp.x, lp.y);
          const y = CH.y + 6 - 274 + 58 + clamp(line0, 0, 490);
          const l = P(CH.x - 345, y);
          const r = P(CH.x + 345, y);
          const g = fx.g;
          g.save();
          g.globalCompositeOperation = "lighter";
          const lin = g.createLinearGradient(lf[0], lf[1], (l[0] + r[0]) / 2, l[1]);
          lin.addColorStop(0, rgb(C.brand, 0.3));
          lin.addColorStop(1, rgb(C.brand, 0.03));
          g.fillStyle = lin;
          g.beginPath();
          g.moveTo(lf[0], lf[1]);
          g.lineTo(l[0], l[1]);
          g.lineTo(r[0], r[1]);
          g.closePath();
          g.fill();
          g.restore();
        }
      }
    }

    // T3 ─ the language model reads the wording; attention runs from the phrases to the lens.
    if (ai) {
      const a = ai.t0;
      const end = converge ?? ai.t1;
      const on = t >= a - 0.1 && t < end + 0.4;
      for (const el of [tokAt, llm, aiPill]) if (!on) put(el, { o: 0 });
      if (on) {
        const out = tw(t, end, 0.3, E.in2);
        put(tokAt, { x: TOK.x, y: TOK.y, o: 1 - out, sx: 1 - 0.08 * out });
        put(llm, { x: 500, y: 462, o: win(t, a + 0.2, end, 0.35, 0.2) });
        const lf = P(lp.x, lp.y);
        toks.forEach((k, i) => {
          const inn = tw(t, a - 0.02 + i * 0.016, 0.34, E.outE);
          const grp = GROUPS.find(([kind]) => kind === k.kind);
          let lit = 0;
          if (grp) lit = tw(t, a + grp[2], 0.3, E.out3);
          const col = grp ? mixc(C.muted, grp[1], lit) : C.muted;
          k.el.style.opacity = (inn * (grp ? 1 : mix(1, 0.55, tw(t, a + 0.7, 0.5)))).toFixed(3);
          k.el.style.transform = `translateY(${((1 - inn) * 18).toFixed(2)}px)`;
          k.el.style.color = rgb(col);
          k.el.style.borderColor = grp ? rgb(grp[1], 0.75 * lit) : "transparent";
          k.el.style.background = grp ? rgb(grp[1], 0.12 * lit) : "";
          if (grp && lit > 0 && out < 1) {
            const p = seg(t, a + grp[2], a + grp[2] + 0.5);
            const from = P(k.at[0], k.at[1] - 28);
            const bow = (k.at[0] < 500 ? 1 : -1) * 0.16;
            fx.curve(from, lf, bow, grp[1], 0.4 * (1 - out) * (0.6 + 0.4 * Math.sin(t * 7 + i)), 2.2 * L.stage.s, p);
            // A pulse keeps running along the thread once it is drawn.
            if (p >= 1) {
              const c = fx.curve(from, lf, bow, grp[1], 0, 1, 1, false);
              const u = (t * 1.3 + i * 0.37) % 1;
              const pt = c.pt(u);
              fx.glow(pt[0], pt[1], 12 * L.stage.s, mixc(grp[1], C.text, 0.4), 0.8 * (1 - out));
            }
          }
        });
        // The model itself: a ring of nodes turning around the lens, lighting up in runs.
        const ring = win(t, a + 0.1, end + 0.1, 0.5, 0.25);
        if (ring > 0.003) {
          const n = 26;
          const rad = (lp.s * 200 + 46) * L.stage.s;
          const g = fx.g;
          g.globalCompositeOperation = "lighter";
          let prev = null;
          for (let i = 0; i <= n; i++) {
            const ang = (i / n) * TAU + t * 0.5;
            const wob = 1 + 0.035 * Math.sin(i * 2.1 + t * 3);
            const x = lf[0] + Math.cos(ang) * rad * wob;
            const y = lf[1] + Math.sin(ang) * rad * wob;
            const fire = Math.pow(0.5 + 0.5 * Math.sin(i * 0.9 - t * 9), 6);
            if (prev) fx.line(prev[0], prev[1], x, y, C.brand, ring * (0.12 + 0.5 * fire), 1.6 * L.stage.s);
            if (i < n) fx.glow(x, y, (5 + 9 * fire) * L.stage.s, mixc(C.brand, C.text, fire), ring * (0.5 + 0.5 * fire));
            prev = [x, y];
          }
        }
        const pp = tw(t, a + 2.05, 0.45, E.spring);
        put(aiPill, { x: 500, y: 876 + 16 * (1 - tw(t, a + 2.05, 0.35)), sx: mix(0.8, 1, pp), o: win(t, a + 2.05, end + 0.05, 0.15, 0.2) });
      }
    }

    // The tray: each finding docks, then all of it goes to the arbiter inside the lens.
    for (let i = 0; i < tray.length; i++) {
      const c = tray[i];
      if (!c.at || t < c.at - 0.02 || (slam && t > slam + 0.05)) {
        put(c.el, { o: 0 });
        continue;
      }
      const inn = tw(t, c.at, 0.45, E.spring);
      let x = c.x;
      let y = c.y + 22 * (1 - tw(t, c.at, 0.3));
      let sx = mix(0.6, 1, inn);
      let o = tw(t, c.at, 0.15);
      if (converge != null && t > converge) {
        const fly = E.in3(seg(t, converge + i * 0.04, slam - 0.06));
        x = mix(x, lp.x, fly);
        y = mix(y, lp.y, fly) - 70 * Math.sin(fly * Math.PI);
        sx *= 1 - 0.65 * fly;
        o *= 1 - E.in3(seg(fly, 0.8, 1));
      }
      put(c.el, { x, y, sx, o });
    }
    void verdict;
  }
  return { update, addedX };
}
