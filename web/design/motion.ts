/**
 * Falcon Lens | عدسة الصقر — motion system constants.
 * Spec: docs/DESIGN.md §7. CSS mirror: web/design/tokens.css (--fl-dur-*, --fl-ease-*).
 *
 * This file imports nothing, so it can be used by the Next.js app (with Motion's
 * `m` components: the shapes below are structurally compatible with Motion's
 * `Transition` and `Variants`), by the extension warning page, and by tests.
 *
 * Rules that the constants encode:
 *  - Animate only `opacity`, `transform` and `clip-path` (compositor-friendly).
 *  - Movement is short (<= 16 px) and always toward the reading position.
 *  - Inline-axis offsets are logical: multiply by `inlineSign(dir)` so RTL mirrors.
 *  - Nothing important is conveyed by motion alone; every state has a static form.
 */

export type Dir = "rtl" | "ltr";
export type Bezier = readonly [number, number, number, number];
export type Verdict = "dangerous" | "suspicious" | "no_warning_signs";
export type Tier = "T0" | "T1" | "T2" | "T3";

/** Durations in seconds (Motion uses seconds; multiply by 1000 for WAAPI). */
export const duration = {
  instant: 0.09, // press feedback, focus ring
  fast: 0.16, // hover, chip, tooltip
  base: 0.26, // evidence row, card enter
  slow: 0.42, // panel move, lens dock
  reveal: 0.64, // verdict plate wash
  ambient: 9, // one lens sweep revolution at rest
  scanSweep: 1.6, // one lens sweep revolution while checking
} as const;

export const easing = {
  out: [0.16, 1, 0.3, 1], // enter
  in: [0.5, 0, 0.9, 0.3], // exit
  inOut: [0.65, 0, 0.35, 1], // move, morph
  linear: [0, 0, 1, 1], // sweeps, progress
} as const satisfies Record<string, Bezier>;

/** Springs (Motion `type: "spring"`). CSS equivalent: --fl-ease-spring over `duration.reveal`. */
export const spring = {
  /** Verdict plate, lens lock: one soft overshoot. */
  settle: { type: "spring", stiffness: 260, damping: 24, mass: 1 },
  /** Layout shifts when a tier adds rows. No overshoot. */
  layout: { type: "spring", stiffness: 380, damping: 40, mass: 1 },
  /** Risk marker travelling along the band. */
  marker: { type: "spring", stiffness: 120, damping: 20, mass: 1 },
} as const;

export const stagger = {
  evidence: 0.07, // rows inside one tier
  reasons: 0.09, // the (max three) reasons
  actions: 0.06, // action list items
  cards: 0.05, // board cards on first paint
  maxItems: 8, // items past this index appear with no extra delay
} as const;

export const distance = {
  rise: 12, // px, block axis enter
  slide: 16, // px, inline axis enter (use inlineSign)
  press: 0.97, // scale on press
} as const;

/** +1 in LTR, -1 in RTL: multiply inline-axis offsets so motion follows reading direction. */
export const inlineSign = (dir: Dir): 1 | -1 => (dir === "rtl" ? -1 : 1);

/** Delay for the i-th item of a staggered group, capped so long lists do not drag. */
export const staggerDelay = (index: number, step: number = stagger.evidence): number =>
  Math.min(index, stagger.maxItems) * step;

/* ── Variants (Motion-compatible) ─────────────────────────────────────── */

export const fadeRise = {
  hidden: { opacity: 0, y: distance.rise },
  visible: { opacity: 1, y: 0, transition: { duration: duration.base, ease: easing.out } },
  exit: { opacity: 0, transition: { duration: duration.fast, ease: easing.in } },
} as const;

/** Evidence row: enters from the inline-start side of the timeline rail. */
export const evidenceRow = (dir: Dir) =>
  ({
    hidden: { opacity: 0, x: -distance.slide * inlineSign(dir) },
    visible: (index: number) => ({
      opacity: 1,
      x: 0,
      transition: { duration: duration.base, ease: easing.out, delay: staggerDelay(index) },
    }),
  }) as const;

/** Container that staggers its children (reasons, actions, board cards). */
export const staggerGroup = (step: number = stagger.reasons, delayChildren = 0) =>
  ({
    hidden: {},
    visible: { transition: { staggerChildren: step, delayChildren } },
  }) as const;

/** Verdict plate: colour wash expands from the lens, then the word and icon settle. */
export const verdictPlate = {
  hidden: { opacity: 0, scale: 0.96, clipPath: "circle(0% at 50% 0%)" },
  visible: {
    opacity: 1,
    scale: 1,
    clipPath: "circle(150% at 50% 0%)",
    transition: {
      opacity: { duration: duration.fast, ease: easing.out },
      clipPath: { duration: duration.reveal, ease: easing.out },
      scale: spring.settle,
    },
  },
} as const;

/** Provisional verdict replaced by a stronger one: cross-fade, never a slide. */
export const verdictUpgrade = {
  exit: { opacity: 0, transition: { duration: duration.fast, ease: easing.in } },
  enter: { opacity: 1, transition: { duration: duration.base, ease: easing.out } },
} as const;

/** A new event on a live board: one ring, then rest. Never loops more than `repeat` times. */
export const livePulse = {
  ring: {
    scale: [1, 2.6],
    opacity: [0.55, 0],
    transition: { duration: 1.4, ease: easing.out, repeat: 2, repeatDelay: 0.2 },
  },
} as const;

/* ── Choreography ─────────────────────────────────────────────────────── */

/** Lens state per check phase. `sweep` is seconds per revolution; `aperture` is 0..1 open. */
export const lens = {
  idle: { sweep: duration.ambient, aperture: 1, arcs: 0 },
  scanning: { sweep: duration.scanSweep, aperture: 0.72, arcs: 0 },
  locked: { sweep: 0, aperture: 0.86, arcs: 4 },
  /** Arc segment (one per tier) fill time once its tier completes. */
  arcFill: { duration: duration.slow, ease: easing.out },
  /** Lens moves from hero to the result header. Use a shared layout id / view-transition-name. */
  dock: { duration: duration.slow, ease: easing.inOut, viewTransitionName: "fl-lens" },
} as const;

/** Resident-facing tier labels are keys into i18n; the code never prints "T0" to residents. */
export const tierOrder: readonly Tier[] = ["T0", "T1", "T2", "T3"] as const;

/**
 * Sequence run each time an SSE `verdict` event arrives (see IMPLEMENTATION_PLAN.md §3).
 * Times are offsets in seconds from the event; the UI never delays showing a `final`
 * verdict by more than `maxHoldBeforeFinal` in total, however much evidence is queued.
 */
export const verdictEventSequence = {
  arcFillAt: 0,
  evidenceRowsAt: 0.08,
  provisionalChipAt: 0.2,
  finalPlateAt: 0.3,
  reasonsAfterPlate: 0.24,
  actionsAfterReasons: 0.18,
  maxHoldBeforeFinal: 0.6,
} as const;

/** Haptics on final verdict (Android; ignored elsewhere). Milliseconds, vibrate pattern. */
export const haptics: Record<Verdict, readonly number[]> = {
  dangerous: [60, 60, 120],
  suspicious: [40],
  no_warning_signs: [],
};

/* ── Reduced motion ───────────────────────────────────────────────────── */

/**
 * With `prefers-reduced-motion: reduce`: no transforms, no clip-path wipes, no ambient
 * loops, no stagger, no smooth scrolling, no haptics. State changes are opacity-only.
 */
export const reduced = {
  duration: { enter: 0.12, exit: 0.01 },
  fade: {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.12, ease: easing.linear } },
    exit: { opacity: 0, transition: { duration: 0.01 } },
  },
  lens: { sweep: 0, aperture: 1 },
  livePulse: false,
  stagger: 0,
} as const;

/** Picks the reduced variant set when the user asks for less motion. */
export const pick = <A, B>(prefersReduced: boolean, full: A, less: B): A | B => (prefersReduced ? less : full);

/* ── Budgets (enforced in Phase B by Playwright + Lighthouse CI) ─────── */

export const budget = {
  fps: 60,
  frameMs: 16.7,
  maxConcurrentAnimatedElements: 24, // on a phone; boards virtualise beyond this
  lcpMs: 2500,
  inpMs: 200,
  cls: 0.05,
  routeJsGzipKb: 180, // first-load JS for "/" including framework
  motionJsGzipKb: 30, // `m` + `domAnimation` via LazyMotion
  fontsKb: 100, // all preloaded woff2 together
} as const;
