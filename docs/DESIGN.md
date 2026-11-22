# DESIGN — Falcon Lens | عدسة الصقر

Owner: builder-frontend. Tokens: `web/design/tokens.css`. Motion constants: `web/design/motion.ts`.
Prototype: `web/design/prototype/index.html`. App mapping: `web/design/IMPLEMENTATION_PLAN.md`.
Every number in §4 comes from `node web/design/scripts/check-contrast.mjs` (run 2026-11-22).

## 1. Vision

**One instrument, one answer.** A falcon sees a small thing from far away and decides at once. The
product is that eye turned on a suspicious link: an aperture that opens, narrows on the evidence and
locks on a verdict. The lens is not decoration. It is the progress indicator, the verdict seal and the
radar of the campaign board, so the same shape tells residents, operators and judges what the system
is doing.

**Narrative, in the order a person meets it.**
1. *Paste.* A calm night screen, one sentence, one box. The lens idles beside it.
2. *Look.* The aperture narrows. Four arcs around it fill as the four tiers finish. Evidence arrives
   in plain Arabic, one row per fact.
3. *Decide.* The lens locks and takes the verdict's colour and shape. A plate states the verdict in
   one word, then at most three reasons, then what to do.
4. *Watch.* The same lens becomes a radar: every check is a dot, similar dots cluster into campaigns,
   and an operator approves what the Sentinel proposes.

**Identity is original.** The mark is a ring, a pupil, a brow stroke and the falcon's malar stripe
(the dark streak under a peregrine's eye). No crest, no shield, no police or government colours or
marks, no real-organisation logos anywhere. Background texture is an abstract eight-point lattice.

## 2. Principles

1. **Arabic first, not Arabic translated.** Layout, type and motion are designed in RTL; English is
   the mirror.
2. **For the least technical reader.** One action per screen, 17 px minimum body text, 48 px touch
   targets, no jargon in resident copy (tiers have human names; `T0`–`T3` are operator detail).
3. **Never imply a guarantee.** The word "safe" (and «آمن») never appears. The lowest verdict is not
   green, has no tick, and always carries a caution block above the actions.
4. **Caution is asymmetric.** While `final=false` the UI may show a provisional *suspicious* or
   *dangerous*, never a provisional "no warning signs". Only a final verdict may say it.
5. **Evidence is visible.** Every reason shows the evidence ids it cites; tapping one highlights the
   row in the investigation timeline. The risk score is shown as the arbiter's, not the AI's.
6. **Colour never works alone.** Verdict = colour + outline shape + word. Severity = colour + shape +
   word. Evidence polarity = shape.
7. **Honest surfaces.** Anything with `source != live` wears a dashed `DEMO DATA` badge. No marketing
   numbers. The board is a similarity radar, not a map, because checks carry no location.
8. **Untrusted text stays text.** Rendered with text nodes only. URLs are defanged, monospace,
   LTR-isolated and never links.
9. **Motion explains, then stops.** Each animation answers "what just changed?". Nothing loops near
   text a person is reading, except one slow lens sweep.

## 3. Layout

- **Grid.** 4 columns at 390 px (16 px gutters), 8 at 720 px, 12 at 1024 px and up (32 px gutters);
  content max 76 rem; text measure max 38 rem. Spacing is a 4 px scale (`--fl-space-*`).
- **RTL.** Logical properties only (`margin-inline`, `inset-inline-start`, `text-align: start`).
  Timelines and rails sit on the inline-start edge. Directional icons mirror; the lens, clocks and
  the radar do not. Technical strings (URLs, ids, phone numbers) are `dir="ltr"` with
  `unicode-bidi: isolate`, which also neutralises bidi-override tricks in pasted text.
- **Digits.** Western digits (0–9) in both languages, so `999` reads the same on screen and keypad.
- **Phone (primary).** The paste box and the "Check now" button are above the fold at 390 × 844; the
  lens shrinks to a 96 px instrument beside the headline. Result order: case header (mini lens, status,
  URL) → verdict plate → reasons → caution (if any) → do now → if you already acted → report →
  investigation timeline. Everything stacks; nothing important is in a tab or a carousel.
- **Desktop.** Hero is two columns (copy and box at inline-start, 480 px lens at inline-end). Result
  is a 1.3 : 0.7 split with a sticky investigation timeline. Boards are radar + cards.
- **Surfaces.** `/` check, `/share` (share target, same page with input filled), `/campaigns` board,
  `/ops` incident board (API key), extension popup and warning page (same tokens).

## 4. Colour

Two themes from one token set: **Night** (default dark, for the video and the operator board) and
**Sand** (light, for phones outdoors). With no stored choice the app follows `prefers-color-scheme`.

| Role | Night | Sand |
|---|---|---|
| `bg` / `surface-1` / `surface-2` / `surface-3` | `#070B14` / `#0E1626` / `#16203A` / `#1F2C4C` | `#F7F3EA` / `#FFFFFF` / `#EFE8D8` / `#E4DBC6` |
| `border` / `border-strong` | `#2A3757` / `#5A6C92` | `#DDD3BF` / `#8C8168` |
| `text` / `text-muted` / `text-faint` | `#F2EEE6` / `#AEB8CC` / `#8794AE` | `#121826` / `#475066` / `#5C667C` |
| `brand` (lens glass, primary action) / `brand-ink` | `#3FE0C5` / `#04211D` | `#0A6E61` / `#FFFFFF` |
| `sand` (warm accent) | `#E7D7B6` | `#7A6535` |
| **dangerous** fg / solid / tint | `#FF8589` / `#D42A38` / `#2B0F15` | `#A80F45` / `#C01F3F` / `#FCE9EA` |
| **suspicious** fg / solid / tint | `#FFC55C` / `#F4B23A` / `#2A1D07` | `#6A5600` / `#F4B23A` / `#FFF1CF` |
| **no_warning_signs** fg / solid / tint | `#A9C0FF` / `#3A5BD0` / `#111C3D` | `#2A4BB0` / `#3353C4` / `#E8EEFF` |

| Verdict | Colour | Outline shape | Word (ar / en) |
|---|---|---|---|
| `dangerous` | red | octagon with `!` | خطِر / Dangerous |
| `suspicious` | amber, hatched in bars | triangle with `?` | مريب / Suspicious |
| `no_warning_signs` | slate blue | lens with a dash (looked, found nothing) | لم نجد علامات تحذير / No warning signs found |

- **Why blue, not green.** Green and a tick say "safe". Slate blue says "nothing to report" and
  sits apart from the aqua brand colour and from both warning hues.
- **Contrast (WCAG 2.x, computed).** 84 text/background pairs pass AA; lowest body-text ratio is
  5.01 in Night (white on the dangerous plate) and 4.72 in Sand. Body text on cards is 15.63 (Night)
  and 17.73 (Sand). Control outlines use `border-strong` at 3:1 or better.
- **Colour-vision deficiency.** Verdict hues were simulated for protanopia, deuteranopia and
  tritanopia (Machado et al. 2009 matrices, ΔE76 between each pair). The smallest separation is 25.3
  (Sand text colours, deuteranopia) against a floor of 20. The first Sand palette failed this check
  (9.6) and was changed to a crimson and a dark gold. The simulation is a guard; the guarantee is
  shape + word.
- **Plates.** A verdict plate is `solid` fill, `on` text and a 3 px `fg` edge, so the amber plate
  still has a visible boundary on white.
- **Not used.** Red-and-gold crests, green confirmations, gradients on text, colour-only status dots.

## 5. Typography

| Use | Family | Why |
|---|---|---|
| All UI text, Arabic and Latin | **Readex Pro** (variable, OFL) | Arabic and Latin drawn as one family, built for legibility (the Arabic extension of Lexend, by Nadine Chahine and Thomas Jockin): open counters, generous spacing, clear at small sizes. One variable file per script covers every weight: 22.9 kB Arabic + 31.4 kB Latin woff2. |
| URLs, ids, numbers to copy | **JetBrains Mono** (variable, OFL) | Unambiguous `l` / `I` / `1` and `0` / `O`, which matters when the lesson is "this address is one character off". 40.4 kB Latin woff2. |

Considered: IBM Plex Sans Arabic (handsome, but static weights at about 43–46 kB each, so three
weights cost more than both Readex files) and Noto Kufi Arabic (strong headlines, weaker for long
instructions). Fonts are self-hosted from `@fontsource-variable/*` 5.3.0; total preload 94.7 kB.

| Token and size | Use |
|---|---|
| `text-xs` 13 px | ids, legal lines only, never instructions |
| `text-sm` 15 px | captions, chips |
| `text-md` 17 px | body (minimum for any sentence a resident must read) |
| `text-lg` 20 px | reasons, actions, the input |
| `text-xl` 24 px | section titles |
| `text-2xl` 32 px (40 px desktop) | the verdict word |
| `text-3xl` 36–64 px fluid | hero headline |

Line height is 1.75 for Arabic and 1.55 for Latin (1.35 / 1.15 for headings). Weights 400, 500 and
650. No letter-spacing on Arabic, no italics, no all-caps Arabic, no justified text. The page
honours the user's browser font size (rem everywhere) and reflows at 200% zoom.

## 6. Iconography

- 24 px grid, 1.9 px stroke, round caps and joins, `currentColor`. Lucide (ISC) as the base set in
  the app, plus custom verdict, polarity, severity and lens icons defined in the prototype.
- Evidence polarity: filled up-triangle raises risk, outlined down-triangle lowers it, ring is
  neutral. Severity: octagon critical, triangle high, diamond medium, circle low.
- No tick marks on resident surfaces, no padlock as a "good" sign (people were taught that wrongly),
  no shield. Icons are always next to a label; none carries meaning alone.

## 7. Motion system

**Constants** (`motion.ts` and `--fl-dur-*`, `--fl-ease-*`):

| Token | Value | Use |
|---|---|---|
| `instant` / `fast` | 90 ms / 160 ms | press, hover, chips |
| `base` | 260 ms | evidence row, card enter |
| `slow` | 420 ms | lens aperture, arc fill, panel move |
| `reveal` | 640 ms | verdict plate wash |
| `ambient` / `scanSweep` | 9 s / 1.6 s per revolution | lens sweep idle / checking |
| stagger | 70 / 90 / 60 ms | evidence / reasons / actions, capped at 8 items |
| `ease-out` | `(0.16, 1, 0.3, 1)` | enter |
| `ease-in` / `ease-in-out` | `(0.5, 0, 0.9, 0.3)` / `(0.65, 0, 0.35, 1)` | exit / move |
| spring `settle` | stiffness 260, damping 24 | verdict plate, lens lock (CSS: `--fl-ease-spring`) |

Only `opacity`, `transform` and `clip-path` animate. Travel is at most 16 px. Inline-axis motion
follows reading direction (`inlineSign`), so rows enter from the right in Arabic.

**Choreography.**
- **Hero lens (idle).** Tick ring turns once in 120 s; one sweep revolution in 9 s; a few specimen
  chips (`hxxps://`, `OTP`, «رمز التحقق») drift ±12 px. Aperture fully open.
- **Input → check.** On submit: chips are drawn into the lens and fade (420 ms), aperture narrows
  78 → 50, sweep speeds to 1.6 s, the page scrolls to the result and the mini lens takes over.
- **Tiered evidence reveal (T0 → T3).** Each SSE `verdict` event: (0 ms) that tier's arc fills and
  its timeline dot turns solid; (80 ms) new evidence rows slide 16 px from inline-start, staggered
  70 ms; the next tier shows one shimmer row and a pinging dot. A provisional *suspicious* or
  *dangerous* appears as a chip beside the status (200 ms). Tiers the cascade did not need become
  dashed, with one sentence saying why.
- **Verdict reveal (`final=true`).** Lens locks (aperture 66, sweep fades, verdict icon springs in
  at the centre, arcs take the verdict colour). The plate washes down from the top centre with a
  `clip-path` circle over 640 ms and settles with one soft spring. Then, staggered: impersonated
  brand, risk marker travelling along the three-zone band, reasons, actions. On Android a
  *dangerous* verdict vibrates `[60, 60, 120]` ms. A final verdict is never held back more than
  600 ms by queued animation.
- **Verdict upgrade** (provisional replaced by stronger): cross-fade, no slide, no bounce.
- **Investigation timeline.** A rail with four nodes. Citing: tapping an evidence chip scrolls to
  the row and gives it a 1.8 s brand outline.
- **Campaign board.** Radar sweep once per 7 s. A new linked check adds a dot that pings three
  times (1.4 s each) and its card gets one 420 ms outline; counters change without rolling digits.
  Hovering a card dims the other clusters. Updates pause when the board is off-screen or the tab is
  hidden.
- **Incident board.** The newest timeline node pings every 1.8 s while the incident is open; new
  entries rise 24 px. Approve and Reject change state in place with no celebration.
- **Navigation.** Language and theme switches use a same-document View Transition cross-fade where
  supported. The hero lens and the result lens share `view-transition-name: fl-lens`.

## 8. Performance budgets

| Budget | Target |
|---|---|
| Frame rate | 60 fps on a mid-range Android (4× CPU throttle in Chrome DevTools as the test proxy) |
| LCP / INP / CLS | < 2.5 s on Slow 4G / < 200 ms / < 0.05 |
| First-load JS for `/` | ≤ 180 kB gzip including framework; motion library ≤ 30 kB of that |
| Fonts | ≤ 100 kB preloaded (three woff2 files), `font-display: swap`, size-adjusted fallback |
| Animated elements at once | ≤ 24 on a phone; boards cap dots at 40 and virtualise lists |

Rules: no WebGL, no canvas loop, no video and no `backdrop-filter` on phones; the lens is one SVG
plus one rotating layer; the eight blades are redrawn only during a 420 ms state change; ambient
animations stop when off-screen (`IntersectionObserver`) and when the tab is hidden; no layout
properties animate in a loop. These budgets are targets until Phase B measures them with Lighthouse
CI and a Playwright trace; no measured figure is claimed here.

## 9. Reduced motion and CSP

**`prefers-reduced-motion: reduce`.** No transforms, wipes, pings, sweeps, drifting chips, shimmer,
smooth scrolling or haptics. State changes are 120–160 ms opacity fades. The lens shows state
statically (arcs filled, verdict icon and colour). Evidence still arrives tier by tier, because that
is information, not decoration. The prototype implements this and is screenshot-tested in that mode.

**CSP (app and extension pages).**
- `default-src 'self'`; `script-src 'self' 'nonce-…' 'strict-dynamic'` (nonce from Next.js
  `proxy.ts`); `style-src 'self' 'nonce-…'`; `font-src 'self'`; `img-src 'self' data: blob:`;
  `connect-src 'self'`; `object-src 'none'`; `base-uri 'self'`; `form-action 'self'`;
  `frame-ancestors 'none'`. No `unsafe-inline`, no `unsafe-eval`, no `wasm-unsafe-eval`.
- Consequences for design: fonts, icons and the lattice are self-hosted files; no CDN, analytics,
  map tiles or remote fonts at runtime; no Lottie or Rive (their players need WASM or an extra
  runtime); no `style="…"` attributes in server-rendered HTML, so initial animation states come from
  CSS classes and custom properties are set through the CSSOM after hydration.
- No `dangerouslySetInnerHTML`, `innerHTML`, `eval`, or `href` built from untrusted text. Verdict
  screenshots (operator only) load from the API origin as images, never in a frame.
- The prototype is the one exception (inline CSS/JS, Google Fonts link), because it is a design
  artefact outside the app. It still renders every string through text nodes.

## 10. Phase B: what the app changed from the prototype

Screenshots of the real app (production build, mocked API): `web/design/app-shots/`
(`pnpm build && SHOTS=1 pnpm exec playwright test --project=shots`).

- **Default theme is Night** when no choice is stored (cookie `fl_theme`); Sand is one tap away.
- **The lens stays dark in Sand.** Its glass and blades are an instrument, not a surface.
- **Phone hero.** The lens is a 56 px instrument beside the eyebrow, and the three destinations sit in
  a second header row, so the paste box and "Check now" are above the fold at 390 × 844 (tested).
- **Risk band** is one track filled to the arbiter's score. No verdict zones are drawn until the API
  exposes the fitted thresholds.
- **Investigation steps.** Below the four tiers, `verdict.trace` is listed step by step (kind, name,
  time, summary) as plain text.
- **Share target** is POST multipart and starts the check; see `DECISIONS.md`.
- **Honest states.** Rate limit, service down, offline, interrupted stream, unknown id, and boards
  that are not connected each have their own plain sentence. None of them shows a verdict.
- **Demo data** exists only behind `?demo=1`, under a full-width `DEMO DATA` ribbon; anything typed
  in the box still goes to the real API.
- **No specimen chips** around the hero lens: they needed inline positioning, which the CSP forbids.
