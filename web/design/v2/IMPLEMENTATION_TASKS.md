# Web v2 — implementation task cards

Spec: `DESIGN_SPEC.md`. Copy: `copy.json` (table view: `COPY.md`). Reference renders: `shots/`.
Branches: `feat/web-v2-<slug>`, one PR per card, in the order below (W2-01 first; W2-02 before W2-03 … W2-08).

**Acceptance that applies to every card** (do not repeat it in the PR, just tick it):

- `pnpm lint`, `pnpm typecheck`, `pnpm test` (vitest) and `pnpm test:e2e` pass in `web/`; `make test` and `make guard` pass at the root.
- axe (`@axe-core/playwright`): 0 serious or critical violations on every route the card touches, in Arabic at 390 and English at 1440, Night and Sand.
- Lighthouse (mobile preset, production build): Performance, Accessibility, Best Practices, SEO each ≥ 90 on the touched routes. Record the scores in the PR; do not type them anywhere on the site.
- CSP intact: the existing CSP test still reports 0 violations; no `style=` attribute in server HTML, no `dangerouslySetInnerHTML`, no new origin in `connect-src` / `font-src`.
- No number is typed: metrics only through `web/lib/results.ts`; a vitest case fails the build if a digit-percent literal appears in `web/lib/i18n.ts` or `page-content.ts` copy.
- The strings "safe" and «آمن» do not appear in rendered text (extend the existing forbidden-word test to the new routes).
- Every Live / In progress badge is driven by `loadCapabilities()`. Each card that shows a badge adds an e2e case with the flag forced false **and** true (mock `/v1/meta`), asserting the badge text both ways.
- No horizontal scroll at 390; the paste box and "Check now" stay above the fold at 390 × 844.
- `DECISIONS.md` gets one line per assumption.

---

## W2-01 Capability flags for the agents and the integration surfaces
- **Files:** `web/scripts/sync-results.mjs`, `web/lib/capabilities.ts`, `web/lib/capabilities.generated.json`, `web/components/CapBadge.tsx`, `web/lib/i18n.ts` (`cap.live`, `cap.progress`), `web/tests/` (vitest for `mergeCapabilities`).
- **Do:** add `sentinel_agent`, `rest_api`, `mcp`, `stix` to the `want` list and to `CapId` / `IDS`. Drop "(PR #47)" from `cap.progress`. Badge style per spec §6 (solid + filled dot / dashed + hollow dot).
- **Do not:** edit `scripts/submission/capabilities.py` (not ours). If a probe looks wrong, say so in the PR for L1.
- **Accept:** a flag missing from both the bundle and `/v1/meta` renders "In progress"; `node scripts/sync-results.mjs` at the repo root writes all ten flags; unit test covers missing, false, true and runtime-overrides-bundle.

## W2-02 Navigation, routes, redirects, footer
- **Files:** `web/components/Chrome.tsx`, `web/lib/i18n.ts` (`nav.*`, `foot.indep`), `web/next.config.ts` (redirects), `web/app/agents/page.tsx` (stub that W2-05 fills), `web/app/docs/page.tsx` (stub that W2-07 fills), `web/app/globals.css`, `web/lib/meta.ts`.
- **Do:** nav order Check · AI agents · Results · For authorities · Docs · Privacy. Campaigns and Incident board move to the footer. Phone header: brand, language, Menu (theme switch inside the menu). Permanent redirects `/how-it-works` → `/agents`, `/architecture/agents` → `/docs/agents`. Home `<title>` / description use `home.eyebrow`.
- **Accept:** e2e: both redirects return 308 and land on a 200; `aria-current="page"` is correct on each route; menu opens, closes with Escape, focus returns; brand does not wrap at 390 in Arabic or English; sitemap / manifest shortcuts updated.

## W2-03 Home: hero with the two AI agents, outcomes, agents section
- **Files:** `web/app/page.tsx`, `web/components/CheckExperience.tsx`, new `web/components/AgentChip.tsx`, new `web/components/Radar.tsx` (static SVG + one rotating layer, same rules as `Lens.tsx`), `web/lib/i18n.ts` (`home.*`, `agent.*`, `out.*`, `meet.*`), `web/app/globals.css`, `web/design/tokens.css` (`--fl-text-stat`, `--fl-text-h2`).
- **Do:** spec §3.1 sections 1, 2, 4, 5, 7, 8. Remove the four tier cards and the "how" footnote from Home (their content goes to W2-07). Desktop: lens + radar composition with the two name tags. Phone: lens stays the 56 px instrument; the two agent chips sit under the promise line.
- **Flags:** Investigator chip = Live; its `agent.inv.aistep` line carries the `investigator` badge. Sentinel chip = `sentinel_agent`. Kind tabs badge only when their flag is false.
- **Accept:** e2e asserts the H1 contains "AI agents" (EN) and «ذكاء اصطناعي» (AR); with `investigator=false` the In-progress badge is visible in the hero at 390 and 1440; with `sentinel_agent=false` the Sentinel chip shows In progress; no text "T0"…"T3" on `/` before a check; `prefers-reduced-motion`: radar and lens static; run `node web/design/scripts/check-contrast.mjs` after adding the sand-on-surface pairs.

## W2-04 Sentinel ticker
- **Files:** new `web/components/SentinelTicker.tsx` (client), `web/lib/api.ts` (reuse the campaigns fetch + stream used by `CampaignBoard.tsx`), `web/lib/i18n.ts` (`ticker.*`), `web/app/page.tsx`.
- **Do:** spec §3.1 section 3: label, active-campaign count and linked-check count computed from the response, latest campaign title (text node, bilingual field), link to `/campaigns`. States: live, non-live source (dashed `demo.badge`), empty, unreachable. Pause updates when off-screen or the tab is hidden. `aria-live="polite"`, at most one announcement per 10 s.
- **Accept:** e2e with a mocked `/v1/campaigns`: counts equal the mocked data; `source: "synthetic"` shows the demo badge; a 503 shows `ticker.offline` and no number; an XSS payload in a campaign title renders as text (reuse the payload fixtures); no layout shift when the ticker text changes (CLS < 0.05).

## W2-05 `/agents`: how the AI agents protect you
- **Files:** `web/app/agents/page.tsx`, `web/lib/page-content.ts` (replace `HOW` with `AGENTS` from `copy.json` `agents.*`), delete `web/app/how-it-works/` (redirect from W2-02), `web/app/globals.css`.
- **Do:** spec §3.3. Two lanes of three steps, the hand-off line between them, three commitments, two CTAs. No pattern or tool names on this page.
- **Flags:** Investigator lane header Live; step 2 carries `investigator`; Sentinel lane header `sentinel_agent`.
- **Accept:** e2e: page has exactly one H1, six numbered steps, the link to `/docs/agents`; the strings "LangGraph", "T3", "state machine" do not appear; flag-false / flag-true cases for both lanes.

## W2-06 Check result: agent activity, plain reasons, collapsed technical details
- **Files:** `web/components/Result.tsx`, `web/components/CheckExperience.tsx`, new `web/components/AgentActivity.tsx`, new `web/components/TechnicalDetails.tsx` (wraps the existing timeline, evidence rows, risk band, trace, meta), `web/lib/i18n.ts` (`act.*`, `tech.*`, `res.*`), `web/lib/verdict-stream.ts` (expose tier status as the four activity steps; no protocol change), `web/app/globals.css`.
- **Do:** spec §3.2 and §7. Phone order exactly as listed there. `AgentActivity` maps T0–T3 status to the four `act.step.*` rows with a state word; title `act.title` while `final=false`, `act.done` with `latency_ms` when final. Reasons render sentence only. `TechnicalDetails` is a closed `<details>`; opening a citation opens it and scrolls to the evidence row (keep the 1.8 s outline). Link `tech.docs` → `/docs/cascade`.
- **Keep:** asymmetric caution (no provisional "no warning signs"), degraded / interrupted / rate-limit / offline states, demo ribbon, defanged non-clickable URL, report block with source and date from `/v1/meta` or config, haptics rule, the 600 ms cap on verdict delay.
- **Accept:** e2e (mocked SSE, the existing demo streams):
  - checking: title contains "Investigator" / «المحقّق»; step states advance with events; no "no warning signs" text before `final=true`;
  - dangerous: plate, three reasons, actions and the three reporting channels are visible **without** opening Technical details; no `ev_` id, "Hard rule", "T2" or risk score is visible until it is opened; after opening, all of them are;
  - no warning signs: caution block is above the actions; no tick icon, no green token in computed styles of the plate;
  - `act.step.ai` shows the In-progress badge when `investigator=false`, and "Not needed" (no badge) when the flag is true and T3 was skipped;
  - XSS payload fixtures pass unchanged; keyboard: `<details>` toggles with Enter and Space; verdict readable (plate in viewport) within 2 s of the final event at 390 with 4× CPU throttle.

## W2-07 `/docs` landing and the eight sub-pages
- **Files:** `web/app/docs/page.tsx`, `web/app/docs/[slug]/page.tsx` (static params: architecture, agents, cascade, arbiter, security, evals, integration, privacy), `web/app/docs/layout.tsx` (side list on desktop, "Docs" breadcrumb on phone), new `web/lib/docs-content.ts`, move `web/lib/arch-content.ts` content under `/docs/agents`, delete `web/app/architecture/`, `web/scripts/sync-results.mjs` (also copy `architecture.svg`, `investigator.svg`, `sentinel.svg`, `agent-*-steps.svg` to `public/images`).
- **Do:** spec §2 table and §3.5. Each sub-page restates its source document; do not add claims. `/docs/cascade` receives the four tier cards removed from Home. `/docs/arbiter` shows thresholds only by reading `data.thresholds` from the artifact. `/docs/integration` receives the REST / MCP / STIX table from `/authorities`, with `rest_api` / `mcp` / `stix` badges. `/docs/security` carries the `injection_defence` badge.
- **Accept:** e2e: landing shows eight cards, each links to a 200; side list marks the current page; an unknown slug is a 404; SVGs load from `'self'` as `<img>` with alt text in both languages; every external statement on `/docs/integration` still says "ready to connect"; vitest: no numeric literal in `docs-content.ts` other than protocol versions ("2.1", "v1", "9457").

## W2-08 Results page and Home proof strip
- **Files:** `web/app/results/page.tsx`, new `web/components/ProofStats.tsx` (server component, used by Home and Results), `web/lib/results.ts` (add `headline(view)` returning recall, fpr, official count from the test split), `web/app/page.tsx`, `web/lib/i18n.ts` (`proof.*`, `results.*`, `ne.*`).
- **Do:** spec §3.4 and §4. Three headline numbers with range and (on Results) one sentence of meaning; scope line with `test.n` and the artifact name always beside them; tables, "what this covers", "not measured yet", provenance, link to `/docs/evals`.
- **Do not:** show `message_path.*` fields (spec §8 flag 4). No count-up animation.
- **Accept:** vitest: `headline()` returns `null` when `available=false` or a field is missing, and then **no** number renders (Home shows `proof.pending`); the rendered values equal `formatMetric` of the artifact fields for a second, different fixture artifact (proves nothing is typed); e2e: the three labels and the scope line are present on `/` and `/results` in both languages; digits are Western in Arabic.

## W2-09 `/authorities` trim and Privacy check
- **Files:** `web/app/authorities/page.tsx`, `web/lib/page-content.ts` (`AUTH`), `web/app/privacy/page.tsx` (copy check only).
- **Do:** keep the status callout ("Ready to connect. Not connected."), the boundary section and reporting. Replace the technical surface table with three outcome lines and a link to `/docs/integration`.
- **Accept:** e2e: the status callout is the first thing after the H1; the page states no connection or endorsement exists; no logo or crest image on the page; forbidden-word test passes.

## W2-10 Live end-to-end, screenshots, design doc
- **Files:** `web/tests/live/*.spec.ts`, `web/design/scripts/capture-committee.mjs` (new route list), `web/design/app-shots/committee/*` (regenerated, < 2 MB), `docs/DESIGN.md` (new §11 "v2: business-oriented site" summarising this spec; update §3 surfaces).
- **Do:** against the running stack (`make up`, `LIVE_BASE_URL`): submit the Falcon Demo Bank fixture URL from the internal fixtures and assert a final verdict renders with the activity card and collapsed technical details; load `/`, `/agents`, `/results`, `/authorities`, `/docs`, `/docs/cascade`, `/privacy`; assert badges match `GET /v1/meta` capabilities; assert the ticker matches `GET /v1/campaigns`.
- **Accept:** the live spec passes locally and its output is attached to the PR; axe and Lighthouse numbers for all six nav routes are in the PR description; committee screenshots regenerated; side-by-side with `web/design/v2/shots/` reviewed by builder-frontend (design lead) before L1 merge.

---

### Not in these cards (needs L1 or another builder first)
- A campaign link on the verdict (contract change proposal, spec §8 flag 3).
- A latency metric in the eval artifact (builder-evals, spec §8 flag 5).
- Meaning of `message_path.dangerous_recall` (builder-evals, spec §8 flag 4).
- L1 ruling on what "the Investigator" names while `investigator` is false (spec §8 flags 1 and 2). W2-03 and W2-06 implement the default in the spec and keep the fallback behind one constant.
