// Backdrop (desert night, lattice, dust, light) and the effects canvas (rings, waveform, beams, sparks).
import { C, TAU, clamp, mix, mixc, noise1, rgb, rng } from "./lib.js";

/** The 8-point star lattice of the site's background (docs/assets/*.svg pattern "lat"), drawn once to a tile. */
function latticeTile(size) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const k = size / 48;
  g.strokeStyle = "rgb(34 48 82)";
  g.lineWidth = 1.4;
  g.beginPath();
  const pts = [[24, 4], [30, 18], [44, 24], [30, 30], [24, 44], [18, 30], [4, 24], [18, 18]]; // prettier-ignore
  pts.forEach(([x, y], i) => (i ? g.lineTo(x * k, y * k) : g.moveTo(x * k, y * k)));
  g.closePath();
  g.stroke();
  return c;
}

export function makeBackdrop(canvas, L) {
  const { W, H } = L;
  canvas.width = W;
  canvas.height = H;
  const g = canvas.getContext("2d");
  const tile = latticeTile(108);
  const pattern = g.createPattern(tile, "repeat");
  const R = rng(20261125);
  const dust = Array.from({ length: 90 }, () => ({ x: R(), y: R(), z: 0.25 + 0.75 * R(), ph: R() * TAU, hue: R(), sp: 0.4 + R() }));
  const diag = Math.hypot(W, H);

  /** grade: {red 0..1, warm 0..1, dim 0..1, lift 0..1, drift px, lat 0..1} */
  return function draw(t, grade) {
    const red = clamp(grade.red ?? 0);
    const warm = clamp(grade.warm ?? 0);
    const dim = clamp(grade.dim ?? 0);
    const lift = clamp(grade.lift ?? 0);
    g.globalCompositeOperation = "source-over";
    g.globalAlpha = 1;
    g.fillStyle = rgb(C.bg);
    g.fillRect(0, 0, W, H);

    // Two large glows: the lens colour from above, deep blue from below.
    const key = mixc(mixc(C.brand, C.danger, red), C.sand, warm * 0.55);
    const gx = W * (0.5 + 0.1 * Math.sin(t * 0.21));
    const gy = H * (0.2 + 0.03 * Math.cos(t * 0.17));
    let rad = g.createRadialGradient(gx, gy, 0, gx, gy, diag * 0.62);
    rad.addColorStop(0, rgb(key, (0.16 + 0.1 * lift + 0.12 * red) * (1 - 0.6 * dim)));
    rad.addColorStop(0.45, rgb(key, (0.05 + 0.04 * red) * (1 - 0.6 * dim)));
    rad.addColorStop(1, rgb(key, 0));
    g.fillStyle = rad;
    g.fillRect(0, 0, W, H);
    const bx = W * (0.78 + 0.06 * Math.cos(t * 0.13));
    const by = H * 0.96;
    rad = g.createRadialGradient(bx, by, 0, bx, by, diag * 0.6);
    rad.addColorStop(0, `rgb(27 42 74 / ${(0.6 * (1 - 0.5 * dim)).toFixed(3)})`);
    rad.addColorStop(1, "rgb(27 42 74 / 0)");
    g.fillStyle = rad;
    g.fillRect(0, 0, W, H);

    // Lattice, drifting slowly; it fades toward the edges.
    const lat = (grade.lat ?? 1) * (1 - 0.5 * dim);
    if (lat > 0.01) {
      g.save();
      g.globalAlpha = 0.55 * lat;
      const dx = (t * 5 + (grade.drift ?? 0) * 0.35) % 108;
      g.translate(-dx, -(t * 2.5) % 108);
      g.fillStyle = pattern;
      g.fillRect(0, 0, W + 216, H + 216);
      g.restore();
      rad = g.createRadialGradient(W / 2, H * 0.42, diag * 0.12, W / 2, H * 0.42, diag * 0.6);
      rad.addColorStop(0, "rgb(7 11 20 / 0)");
      rad.addColorStop(1, "rgb(7 11 20 / 0.92)");
      g.fillStyle = rad;
      g.fillRect(0, 0, W, H);
    }

    // A slow diagonal light band.
    g.save();
    g.globalCompositeOperation = "lighter";
    g.translate(W / 2, H / 2);
    g.rotate(-0.42);
    const band = ((t * 0.045 + 0.2) % 1) * 2 - 1;
    const lin = g.createLinearGradient(band * diag * 0.8 - diag * 0.22, 0, band * diag * 0.8 + diag * 0.22, 0);
    lin.addColorStop(0, rgb(key, 0));
    lin.addColorStop(0.5, rgb(key, 0.05 * (1 - dim)));
    lin.addColorStop(1, rgb(key, 0));
    g.fillStyle = lin;
    g.fillRect(-diag, -diag, diag * 2, diag * 2);
    g.restore();

    // Dust in the light: three depths, slow drift, soft dots.
    g.globalCompositeOperation = "lighter";
    for (const p of dust) {
      const x = ((p.x + t * 0.006 * p.sp * p.z + (grade.drift ?? 0) * 0.00012 * p.z) % 1 + 1) % 1;
      const y = ((p.y - t * 0.011 * p.sp * p.z) % 1 + 1) % 1;
      const r = (1.4 + 5.2 * p.z * p.z) * (W / 1080 > 1.2 ? 1.1 : 1);
      const a = (0.05 + 0.2 * p.z) * (0.55 + 0.45 * Math.sin(t * 0.9 * p.sp + p.ph)) * (1 - 0.5 * dim);
      const col = p.hue < 0.6 ? key : p.hue < 0.85 ? C.sand : C.text;
      const cx = x * W;
      const cy = y * H;
      const dot = g.createRadialGradient(cx, cy, 0, cx, cy, r * 2.2);
      dot.addColorStop(0, rgb(col, a));
      dot.addColorStop(1, rgb(col, 0));
      g.fillStyle = dot;
      g.fillRect(cx - r * 2.2, cy - r * 2.2, r * 4.4, r * 4.4);
    }
    g.globalCompositeOperation = "source-over";

    // Vignette.
    rad = g.createRadialGradient(W / 2, H * 0.45, diag * 0.28, W / 2, H * 0.45, diag * 0.72);
    rad.addColorStop(0, "rgb(2 4 9 / 0)");
    rad.addColorStop(1, `rgb(2 4 9 / ${(0.78 + 0.15 * dim).toFixed(3)})`);
    g.fillStyle = rad;
    g.fillRect(0, 0, W, H);
  };
}

export function makeFx(canvas, L) {
  canvas.width = L.W;
  canvas.height = L.H;
  const g = canvas.getContext("2d");
  const api = {
    g,
    clear() {
      g.globalCompositeOperation = "source-over";
      g.globalAlpha = 1;
      g.shadowBlur = 0;
      g.clearRect(0, 0, L.W, L.H);
    },
    /** A ring that widens and fades: the product's voice pulse. */
    ring(x, y, r, col, a, w = 3) {
      if (a <= 0.003 || r <= 0) return;
      g.globalCompositeOperation = "lighter";
      g.strokeStyle = rgb(col, a);
      g.lineWidth = w;
      g.beginPath();
      g.arc(x, y, r, 0, TAU);
      g.stroke();
    },
    /** The reactive voice ring: radial bars around the lens, mirrored left and right. */
    wave(x, y, r, levels, col, a, len, t, n = 120) {
      if (a <= 0.003) return;
      g.save();
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      g.lineWidth = Math.max(2, (TAU * r) / n * 0.42);
      const hi = mixc(col, C.text, 0.55);
      for (let i = 0; i < n; i++) {
        const u = i / n;
        const m = Math.abs(u * 2 - 1); // 0 at the top, 1 at the bottom, mirrored
        const fb = m * (levels.length - 1);
        const b0 = Math.floor(fb);
        const lv = mix(levels[b0], levels[Math.min(levels.length - 1, b0 + 1)], fb - b0);
        const jitter = 0.72 + 0.28 * noise1(i * 0.9 + t * 9, 3) + 0.25 * noise1(i * 0.31 - t * 5, 7);
        const l = len * (0.05 + clamp(lv * jitter, 0, 1.3));
        const ang = u * TAU - Math.PI / 2;
        const c = Math.cos(ang);
        const s = Math.sin(ang);
        g.strokeStyle = rgb(mixc(col, hi, clamp(lv)), a * (0.35 + 0.65 * clamp(lv + 0.15)));
        g.beginPath();
        g.moveTo(x + c * r, y + s * r);
        g.lineTo(x + c * (r + l), y + s * (r + l));
        g.stroke();
      }
      g.restore();
    },
    /** A soft additive glow disc. */
    glow(x, y, r, col, a) {
      if (a <= 0.003) return;
      g.globalCompositeOperation = "lighter";
      const rad = g.createRadialGradient(x, y, 0, x, y, r);
      rad.addColorStop(0, rgb(col, a));
      rad.addColorStop(1, rgb(col, 0));
      g.fillStyle = rad;
      g.fillRect(x - r, y - r, r * 2, r * 2);
    },
    /** A horizontal lens streak (anamorphic flare). */
    streak(x, y, w, hgt, col, a) {
      if (a <= 0.003) return;
      g.save();
      g.globalCompositeOperation = "lighter";
      g.translate(x, y);
      g.scale(w / 2, hgt / 2);
      const rad = g.createRadialGradient(0, 0, 0, 0, 0, 1);
      rad.addColorStop(0, rgb(mixc(col, C.text, 0.7), a));
      rad.addColorStop(0.25, rgb(col, a * 0.5));
      rad.addColorStop(1, rgb(col, 0));
      g.fillStyle = rad;
      g.fillRect(-1, -1, 2, 2);
      g.restore();
    },
    /** A line with a soft glow; `p` trims it from the start (0..1). */
    line(x0, y0, x1, y1, col, a, w = 3, p = 1) {
      if (a <= 0.003 || p <= 0) return;
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      g.strokeStyle = rgb(col, a);
      g.lineWidth = w;
      g.beginPath();
      g.moveTo(x0, y0);
      g.lineTo(mix(x0, x1, p), mix(y0, y1, p));
      g.stroke();
    },
    /** A quadratic curve from a to b bowed by `bow`, drawn up to `p`, with a bright head. */
    curve(a, b, bow, col, alpha, w, p, head = true) {
      const mx = (a[0] + b[0]) / 2 - (b[1] - a[1]) * bow;
      const my = (a[1] + b[1]) / 2 + (b[0] - a[0]) * bow;
      const pt = (u) => [(1 - u) * (1 - u) * a[0] + 2 * (1 - u) * u * mx + u * u * b[0], (1 - u) * (1 - u) * a[1] + 2 * (1 - u) * u * my + u * u * b[1]];
      if (alpha <= 0.003 || p <= 0) return { pt, end: pt(clamp(p)) };
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      g.strokeStyle = rgb(col, alpha);
      g.lineWidth = w;
      g.beginPath();
      const steps = 28;
      for (let i = 0; i <= steps; i++) {
        const u = (i / steps) * clamp(p);
        const [x, y] = pt(u);
        if (i) g.lineTo(x, y);
        else g.moveTo(x, y);
      }
      g.stroke();
      const end = pt(clamp(p));
      if (head && p < 1) api.glow(end[0], end[1], w * 6, mixc(col, C.text, 0.5), alpha);
      return { pt, end };
    },
    /** A burst of sparks flying out from a point; `p` is the age 0..1. */
    sparks(x, y, p, col, seed, n = 46, reach = 520) {
      if (p <= 0 || p >= 1) return;
      const R = rng(seed);
      g.globalCompositeOperation = "lighter";
      g.lineCap = "round";
      for (let i = 0; i < n; i++) {
        const ang = R() * TAU;
        const sp = 0.35 + 0.65 * R();
        const d0 = reach * sp * (1 - Math.pow(1 - p, 2.2));
        const d1 = Math.max(0, d0 - 46 * sp * (1 - p));
        const a = (1 - p) * (0.35 + 0.65 * R());
        g.strokeStyle = rgb(mixc(col, C.text, R() * 0.6), a);
        g.lineWidth = 1.5 + 2.5 * R();
        g.beginPath();
        g.moveTo(x + Math.cos(ang) * d1, y + Math.sin(ang) * d1);
        g.lineTo(x + Math.cos(ang) * d0, y + Math.sin(ang) * d0);
        g.stroke();
      }
    },
  };
  return api;
}
