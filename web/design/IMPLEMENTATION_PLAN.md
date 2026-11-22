# Implementation plan — design system → Next.js app (Phase B)

Starts when T-001 (`feat/platform-skeleton`) merges. Spec: `docs/DESIGN.md`. Reference behaviour:
`web/design/prototype/index.html` (its `onVerdictEvent`, `tierStatus` and render functions are the
model for the React components; its fixtures are contract-valid and become the first test fixtures).

## 1. Stack (versions checked 2026-11-22 with `npm view`; add to DECISIONS when adopted)

| Need | Choice | Notes |
|---|---|---|
| Framework | next 16.4.6, react 19.3.1 | App Router, strict TS, pnpm |
| Component motion | **motion 14.14.0** (MIT) | `LazyMotion` + `m` from `motion/react-m` + `domAnimation`; `MotionConfig reducedMotion="user"` |
| Ambient and scroll motion | **CSS only** | keyframes, `linear()` spring, scroll-driven `animation-timeline: view()` behind `@supports`, View Transitions |
| Fonts | `@fontsource-variable/readex-pro` 5.3.0, `@fontsource-variable/jetbrains-mono` 5.3.0 | copied to `public/fonts`, loaded with `next/font/local`, Arabic + Latin subsets only |
| Icons | lucide-react 1.77.0 (ISC) + `components/icons/` | verdict, polarity, severity and lens icons are ours |
| Tests | @playwright/test 1.65.1 | XSS fixtures, RTL/LTR at 390 and 1440, reduced motion, CSP violations = 0 |

Not adopted, with reasons: **GSAP 3.15.1** (free since 2025 under Webflow's "no charge" licence,
which is not an OSI licence and restricts some uses; Motion + CSS cover every effect here, so a
second animation runtime is not worth it); **three / react-three-fiber / OGL** (bundle and GPU cost
on mid-range Android for no gain over SVG); **Lottie / dotLottie / Rive** (need authored assets and
a player; the dotLottie and Rive players use WASM, which would need `wasm-unsafe-eval` in the CSP).

## 2. Files and components (`web/`)

```
app/layout.tsx              html lang/dir from locale cookie, fonts, tokens.css, ThemeScript-free theme (cookie → data-theme)
app/page.tsx                Hero + CheckBox (+ result when ?id=)
app/share/page.tsx          share_target GET handler → redirects to /?text=…  (never auto-submits)
app/campaigns/page.tsx      CampaignBoard
app/ops/page.tsx            IncidentBoard (integration key)
app/manifest.ts, public/sw.js, proxy.ts (CSP nonce)
styles/tokens.css           moved from web/design/tokens.css (single source; extension imports it)
lib/motion.ts               moved from web/design/motion.ts
lib/verdict-stream.ts       EventSource client + reducer
lib/i18n.ts                 ar/en dictionaries (UI chrome only; verdict text comes from the API)
```

| Component | Role | Motion |
|---|---|---|
| `Lens` (`size`, `state`, `verdict`, `tiers`) | hero instrument, mini lens in the case header, favicon source | SVG; CSS sweep and ticks; blades redrawn with one `requestAnimationFrame` tween per state change |
| `CheckBox` | type tabs, paste field, submit | CSS focus glow; Motion press scale |
| `CaseHeader` | status, provisional chip, `DefangedUrl` | chip via `AnimatePresence` |
| `DefangedUrl` | mono, LTR-isolated, registrable domain in bold, never an `<a>` | none |
| `VerdictPlate` | icon + word + one-line instruction | `verdictPlate` variant |
| `RiskBand` | three zones from the API's thresholds, marker at `risk_score` | `spring.marker` |
| `ReasonList` / `EvidenceCite` | ≤ 3 reasons, evidence chips that focus a timeline row | `staggerGroup(stagger.reasons)` |
| `ActionBlocks` | caution → now → if already acted → report (+ channels, source, independence line) | `staggerGroup(stagger.actions)` |
| `InvestigationTimeline` / `TierGroup` / `EvidenceRow` | rail of four tiers, rows by tier, technical toggle | `evidenceRow(dir)`, layout spring |
| `SourceBadge` | `DEMO DATA · <source>` whenever `source != "live"` | none |
| `CampaignRadar`, `CampaignCard`, `Sparkline` | campaign board | CSS sweep; `livePulse` on new dots |
| `IncidentCard`, `IncidentTimeline`, `ActionApproval` | operator board | newest node ping; in-place status change |
| `LangToggle`, `ThemeToggle` | cookie-backed, View Transition cross-fade | CSS |

## 3. SSE integration with the verdict contract

1. `POST /v1/check/url` → `202 { verdict_id, sse_url }`. The page navigates to `/?id=<verdict_id>`
   (shareable, reload-proof) and opens `EventSource(sse_url)`.
2. Each `event: verdict` is one full `Verdict` (same `verdict_id`, growing `evidence`, `final` on the
   last). The reducer keeps the latest object and derives:
   - `tiers`: tier ≤ `tier_reached` → done; next tier → running while `final=false`; after `final`,
     the rest → skipped.
   - `newEvidenceIds`: ids not in the previous event (these rows animate; the others do not).
   - `shown`: `final ? verdict : (verdict === "no_warning_signs" ? "checking" : provisional(verdict))`.
3. Rendering rules tied to fields: `degraded` → "we couldn't complete every check" line under the
   plate (the API already never sends degraded + `no_warning_signs`); `actions.caution` → caution
   block first; `impersonated_brand` → brand line; `source != live` → `SourceBadge`;
   `reasons[].evidence_ids` → cite chips; `evidence[].hard_rule` → rule tag; `trace` → operator-only
   detail inside `TierGroup`; `model_route` and `tier_reached` → footer meta.
4. Failure paths: SSE error before `final` → one retry, then `GET /v1/check/url?wait=8`; if that
   fails, show the last partial with the plate replaced by "check interrupted, do not open the link".
   A cached final verdict arrives as a single event: skip tier choreography, play only the reveal.
5. Every event is validated in dev and tests against `contracts/verdict.schema.json` (types
   generated from the schema, not hand-written).

## 4. PWA and share target

- `app/manifest.ts`: `lang: "ar"`, `dir: "rtl"`, `display: "standalone"`, theme colour `#070B14`,
  maskable icon drawn from the lens mark, `share_target: { action: "/share", method: "GET",
  params: { title, text, url } }` (Android Chrome, installed PWA only; cast the type if needed).
- `/share` fills the box and focuses "Check now"; it does not auto-submit, so a person confirms what
  is sent. iOS: paste box plus the Shortcut (P1), stated plainly on the install hint.
- `public/sw.js`: cache the shell, fonts and tokens only; never cache `/v1/*`; offline page says the
  check needs a connection.

## 5. Extension (Chrome MV3) reuse

- `extension/warning.html` and the popup link the same `tokens.css` and a static build of `Lens`,
  `VerdictPlate` and `ActionBlocks` (no React needed: the prototype's DOM builders are the template).
- The warning page shows the plate, ≤ 3 reasons, "Go back" as the primary button and "Continue
  anyway" as a plain text button after a 3 s delay. Extension CSP: `script-src 'self'`; no remote code.
- Permissions per DECISIONS: `activeTab`, `storage`, host permission for the API origin only;
  `webNavigation` only if automatic checks ship.

## 6. Order of work (Phase B)

1. Move tokens and motion, fonts, layout with locale + theme cookies, `proxy.ts` CSP, Playwright CSP test.
2. `Lens`, `CheckBox`, `DefangedUrl`, `SourceBadge`; fixture-driven result page (T-027 acceptance).
3. `verdict-stream.ts` against the real SSE (after T-013); degraded and failure paths.
4. Manifest, service worker, `/share`.
5. Campaign board, then incident board (after the Sentinel publishes `fl:board`).
6. Extension popup and warning page.

## 7. Proposals for L1 (contracts are not edited here)

- `incident.timeline[].what` is a single string. The board needs Arabic: propose `what: { ar, en }`
  or a `code` the UI can translate (the prototype uses a lookup table as a stopgap).
- The risk band needs the fitted thresholds: propose `GET /v1/meta` returning `tau_low`, `tau_high`
  and the `params.yaml` fit date, so the UI never hard-codes 0.35 / 0.80.
- A campaign summary for residents (title, advice, counts) has no contract yet; the board currently
  derives cards from incidents of `type: "campaign"`. Propose bilingual `title` and `advice` on the
  incident or a small `/v1/campaigns` shape.
- CSP needs a per-request nonce from Next.js, so the Caddy gateway should pass the app's
  `Content-Security-Policy` header through for `/` routes instead of setting its own.

## 8. Design checks that already run

```
node web/design/scripts/check-contrast.mjs            # 84 AA pairs + CVD separation + theme parity
node web/design/scripts/sync-prototype-tokens.mjs --check
uv run web/design/scripts/validate_fixtures.py        # fixtures vs verdict/incident schemas, defanging, wording
PLAYWRIGHT_MODULE=… node web/design/scripts/capture-shots.mjs   # 390 + 1440, ar + en, overflow and console checks
```
Phase B wires these into `make test` once the Makefile exists.

## 9. Phase B status (2026-11-22, `feat/web-app`)

Built: §2 files (tokens and motion stay in `web/design/` and are imported from there, so the design
scripts keep one source), §3 SSE integration, §4 PWA (share target is POST, see `DECISIONS.md`),
campaign and incident boards. Not built yet: §5 extension, Lighthouse CI budgets.
Run: `pnpm build && pnpm test` in `web/` (typecheck, vitest, Playwright against
`tests/mock/gateway.mjs`).
