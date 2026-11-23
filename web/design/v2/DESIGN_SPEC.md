# Web v2 design spec — business-oriented site

Owner: builder-frontend (design lead). Status: **design only**; nothing in `web/app` changes in this PR.
Audience: the ScamShield AI evaluation committee (senior, non-technical first; a few technical members).
Builds on `docs/DESIGN.md` (v1), which stays in force wherever this spec is silent.

| File | What |
|---|---|
| `DESIGN_SPEC.md` | this spec |
| `copy.json` → `COPY.md` | **final EN + AR copy** for every heading, CTA and blurb, with the capability flag each string depends on |
| `mockups/*.html` | static, self-contained mockups (one responsive file serves 390 and 1440) |
| `shots/*.png` | renders: phone 390 and desktop 1440, Arabic RTL; plus Home in English at 1440 |
| `build-mockups.mjs`, `render-shots.mjs`, `quantize.py` | the generator, the renderer, the PNG shrinker |
| `IMPLEMENTATION_TASKS.md` | task cards W2-01 … W2-10 for the builders |

The mockups are generated, not hand-typed: metrics come from `web/lib/results.generated.json`, badges from
`web/lib/capabilities.generated.json`, reporting channels from `config/reporting_channels.yaml`, and demo
content from `web/lib/demo.ts`. The generator fails on any external URL and on the word "safe" / «آمن».

## 1. What the owner asked for, and the answer

| Feedback | Answer |
|---|---|
| The home page never says "AI agent" | "AI agent" is in the eyebrow, the H1, both agent chips, the progress title of every check ("The Investigator is checking…"), the Sentinel ticker, a "Meet the two AI agents" section and the second nav item. |
| Evals are not where judges look | A three-number proof strip sits on Home, and the same three numbers lead the Results page in business words, with the full table below. |
| Too much technical capability on the check page | The four T0–T3 cards, evidence ids, hard-rule chips, risk score, trace and check metadata leave the resident surface. They sit behind one collapsed "Technical details" row and in a new `/docs` area. |

## 2. Information architecture

| Nav (order) | Route | Reader | Job |
|---|---|---|---|
| Check · افحص | `/` | resident, judge | paste, get a verdict; meet the agents; see proof |
| AI agents · الوكيلان الذكيان | `/agents` | judge (business) | how the two agents protect people, in six plain steps |
| Results · النتائج | `/results` | judge | what was measured, what was not |
| For authorities · للجهات المختصة | `/authorities` | authority | "ready to connect, not connected"; what crosses the boundary |
| Docs · التوثيق | `/docs` + 8 sub-pages | technical judge | all technical detail |
| Privacy · الخصوصية | `/privacy` | everyone | what is kept and what is not |

- Header: six links on desktop; on a phone, brand + language + "Menu" (the theme switch moves into the menu so the brand never wraps at 390).
- Footer only: Live campaigns (`/campaigns`), Incident board (`/ops`). Both stay as they are. The Sentinel ticker links to `/campaigns`.
- Redirects (permanent): `/how-it-works` → `/agents`; `/architecture/agents` → `/docs/agents`.
- `/docs` sub-pages and their sources. No new claims: each page restates a repo document.

| Route | Title | Source of truth |
|---|---|---|
| `/docs/architecture` | Architecture | `docs/ARCHITECTURE.md`, `docs/assets/architecture.svg` |
| `/docs/agents` | Agent patterns | today's `/architecture/agents` (`web/lib/arch-content.ts`), ADR-001, ADR-002 |
| `/docs/cascade` | Cascade T0–T3 | the four tier cards removed from Home, ADR-001 |
| `/docs/arbiter` | Arbiter and scoring | `docs/SCORING.md` (no weights typed: link the fitted `thresholds` block of the artifact) |
| `/docs/security` | Security | `docs/THREAT_MODEL.md`; CSP section of `docs/DESIGN.md` §9 |
| `/docs/evals` | Evaluation methodology | `docs/EVALS.md`; provenance block of the artifact |
| `/docs/integration` | Integration: API, MCP, STIX | `docs/INTEGRATION.md`; the surface table moves here from `/authorities` |
| `/docs/privacy` | Privacy engineering | `docs/PRIVACY.md` |

## 3. Pages

Copy keys refer to `copy.json`. Every string exists there in English and in formal Modern Standard Arabic.

### 3.1 Home / Check (`/`) — `shots/home-ar-390.png`, `home-ar-1440.png`, `home-en-1440.png`

| # | Section | Purpose | Copy keys | Data |
|---|---|---|---|---|
| 1 | Hero + check box | one action, above the fold at 390 × 844 | `home.eyebrow` `home.title` `home.sub` (desktop) / `home.sub.phone` `home.kind.*` `home.input.*` `home.cta` `home.promise` | kind tabs: `message_check` `email_check` `image_check` |
| 2 | Agent chips (phone) / lens + radar with name tags (desktop) | names the two AI agents and shows their state | `agent.*` | Investigator AI step: `investigator`; Sentinel: `sentinel_agent` |
| 3 | Sentinel ticker | shows the second agent working, live | `ticker.*` | `GET /v1/campaigns` (+ stream); counts are computed from the response |
| 4 | What you get | four outcomes: speed, clarity, next step, trust | `out.*` | none |
| 5 | Meet the two AI agents | one card each, then the principle line | `meet.*` `agent.*` | same flags as 2 |
| 6 | Measured, not claimed | three numbers, scope line, link to Results | `proof.*` | see §4 |
| 7 | Ready to connect. Not connected. | the authority message in one band | `auth.band.*` | none |
| 8 | Footer | independence line on every page | `foot.indep` | none |

Removed from Home: the "four checking layers" cards with T0–T3 tags, and the "arbiter, not a language model" footnote. Both move to `/docs/cascade`. The principle survives as one business sentence: `meet.principle`.

Ticker states: live data (no badge) · `source != live` (dashed `demo.badge`) · empty (`ticker.empty`) · API unreachable (`ticker.offline`). It never shows a count that did not come from the API. If `sentinel_agent` is false the label carries the In-progress badge.

### 3.2 Check result (same route) — `shots/check-*.png`

Order on a phone: case header → verdict plate → impersonated name → **Why?** (at most three reasons, text only) → caution (only for "no warning signs") → what to do now → if you already acted → report (999 / Aman / complaints portal, from `config/reporting_channels.yaml`) → **Technical details** (collapsed) → agent activity card. On desktop the activity card is a sticky side column (1.35 : 0.65).

| State | What the reader sees |
|---|---|
| Checking | `act.title` ("The Investigator is checking your link…"), four plain steps with a word for each state, a provisional *suspicious* / *dangerous* chip when the stream gives one, `act.wait`, and the Sentinel line. Never a provisional "no warning signs" (DESIGN.md principle 4). |
| Dangerous | red plate, `v.dangerous` + `v.dangerous.sub`, reasons, actions, report. Activity title becomes `act.done` with `latency_ms` from the verdict. |
| No warning signs found | slate-blue plate (not green, no tick), `v.nws.sub` ("This is not a guarantee"), the caution block above the actions. |

The four activity steps are the four tiers under human names: `act.step.known` (T0), `act.step.address` (T1), `act.step.visit` (T2), `act.step.ai` (T3). No `T0`–`T3` code appears outside Technical details.

**Technical details** is a native `<details>` (closed by default, state kept in `sessionStorage`). Inside, unchanged from v1: evidence rows by tier with ids, hard-rule chips, the risk score with "computed by the arbiter", trace steps, check id, tier reached, model route, time, source. One link: `tech.docs` → `/docs/cascade`. The reason → evidence citation still works: opening a citation opens the details panel first.

### 3.3 AI agents (`/agents`) — `shots/agents-ar-*.png`

| # | Section | Purpose | Copy keys |
|---|---|---|---|
| 1 | Title + one-line lead | "one answers you now, the other protects everyone after you" | `agents.title` `agents.lead` |
| 2 | Two lanes, three steps each, joined by the hand-off line | what each agent does, in verbs | `agents.inv.*` `agents.sen.*` `agents.handoff` |
| 3 | Three commitments | the guardrails in business words | `agents.p1–p3.*` |
| 4 | CTAs | try a check; technical architecture in Docs | `agents.cta` `agents.docs` |

No pattern names (state machine, LangGraph), no tool names, no budgets here. They live in `/docs/agents`.

### 3.4 Results (`/results`) — `shots/results-ar-*.png`

1. Title and lead (`results.title`, `results.lead`).
2. The three headline numbers, each with one plain sentence of meaning (`results.*.mean`) and its 95% range.
3. Scope line and artifact file name.
4. All measures: test and validation tables (existing component), with the sample size.
5. "What this covers" (`results.scope.*`), "Not measured yet" (from `data.not_evaluated`, labels `ne.*`), "Where the numbers come from", link to `/docs/evals`.

The existing "evaluation in progress" state and the draft-classifier note (`t1_measured_model`) stay.

### 3.5 Docs landing (`/docs`) — `shots/docs-ar-*.png`

Eyebrow "For technical reviewers", title, lead, eight numbered cards (§2), a side list on desktop, and one way back for non-technical readers (`docs.back`). The Security card shows the `injection_defence` badge.

### 3.6 For authorities and Privacy

Layout unchanged. `/authorities` keeps the status callout, the boundary ("what crosses, what does not") and the reporting section; its REST / MCP / STIX table moves to `/docs/integration` and is replaced by three outcome lines and a link. Each surface shows its flag (`rest_api`, `mcp`, `stix`).

## 4. Metrics: which field appears where

Only these fields of `web/lib/results.generated.json` → `data.metrics` are shown. Format with `formatMetric` / `formatCi` from `web/lib/results.ts`. If `available` is false, the section shows `proof.pending` and no number.

| Surface | Label key | Field | Notes |
|---|---|---|---|
| Home proof strip, Results headline | `proof.recall` | `test.recall`, `test.recall_ci95` | percent, one decimal |
| Home proof strip, Results headline | `proof.fpr` | `test.fpr`, `test.fpr_ci95` | percent, one decimal |
| Home proof strip, Results headline | `proof.official` | `test.official_false_dangerous` | absolute count |
| Scope line | `proof.scope` | `test.n`, `artifact` | always shown beside the numbers |
| Results tables | `metric.*` | `{test,val}.{precision,recall,f1,fpr,pr_auc,ece}` + `_ci95`, `{test,val}.n` | existing table |
| Results provenance | `results.prov.*` | `artifact`, `data.created_at`, `data.dataset_hash`, `data.git_sha`, `data.scope` | existing block |
| Results "not measured yet" | `ne.*` | `data.not_evaluated[]` | unknown keys render as the raw key |
| Check result | `act.done` | `latency_ms` of **that verdict** | not an eval metric |
| Sentinel ticker | `ticker.count` | computed from `GET /v1/campaigns` | live or labelled demo |

Not shown anywhere in v2 until someone confirms what they mean: `*.message_path.*` (see §8, flag 4). There is **no speed metric** in the artifact, so "in seconds" stays qualitative and no latency figure appears outside a real check (flag 5).

## 5. Where "AI agent" appears

| Place | Text | Flag |
|---|---|---|
| Nav item 2 | AI agents · الوكيلان الذكيان | – |
| Hero eyebrow, H1, sub | `home.eyebrow` `home.title` `home.sub` | sub names the Sentinel: `sentinel_agent` |
| Hero chips / desktop name tags | "The Investigator · AI agent", "The Sentinel · AI agent" | `investigator` (AI step), `sentinel_agent` |
| Check progress title | `act.title`, then `act.done` | – |
| Check progress step 4 | `act.step.ai` | `investigator` |
| Check Sentinel line | `act.sentinel` | `sentinel_agent` |
| Ticker | `ticker.label` | `sentinel_agent` |
| Home section 5, `/agents`, `/docs/agents` | names, roles, steps | per string, see `COPY.md` |
| Page `<title>` and description of `/` | "Falcon Lens: two AI agents against scams" (reuse `home.eyebrow`) | – |

## 6. Visual direction and tokens

**Keep the Night palette, the lens and Readex Pro.** v1's identity is right; v2 changes what the page says, not the instrument. Three additions, no new hues:

1. **Two agents, two existing accents.** The Investigator is the lens in `--fl-brand` (aqua). The Sentinel is a radar in `--fl-sand` (the warm accent that so far only drew the brow stroke). Glyph, top rule of the card, role line and numbered steps take the agent's accent. Colour is never alone: each agent always has its glyph and its name.
2. **Status badges.** `Live` = solid outline + filled dot, brand colour. `In progress` = dashed outline + hollow dot, amber. Same component as v1 `CapBadge`, without the PR number in the label.
3. **Proof numerals.** New token `--fl-text-stat: clamp(2.4rem, 1.8rem + 2.4vw, 3.5rem)`, JetBrains Mono 650, `dir="ltr"` isolated, Western digits.

Type scale otherwise as DESIGN.md §5. New section title size `--fl-text-h2: clamp(1.6rem, 1.2rem + 1.6vw, 2.4rem)`. Body stays 17 px minimum; badges are 13 px (labels, not instructions).

Layout: section rhythm `--fl-space-7` on phone, `--fl-space-8` on desktop; cards `--fl-radius-lg`; one full-bleed tinted band per page at most (ticker and proof on Home). Authority band uses a dashed border: the dash is the site's sign for "not yet real" (demo data, in progress, not connected).

Sand (light) theme: all additions use existing tokens, so Sand works without new values. Re-run `web/design/scripts/check-contrast.mjs` after adding the two new foreground/background pairs (sand on surface-1, brand on surface-1 for badges).

### Motion

Principles are DESIGN.md §7 unchanged: motion explains, then stops; only `opacity`, `transform`, `clip-path`; travel ≤ 16 px; inline motion follows reading direction. New pieces:

| Piece | Motion | Reduced motion |
|---|---|---|
| Hero duo (desktop) | lens idles as v1; radar sweep 7 s per turn; nothing else moves | both static |
| Agent activity steps | on each SSE event the finished step's dot fills (260 ms) and the next step shows one shimmer line; the lens arc fills in the same frame | dot and word change, no shimmer |
| Hand-off (verdict final) | one dot travels from the mini lens to the Sentinel line (420 ms, once), then the line's glyph pulses once | no dot; the line is simply present |
| Sentinel ticker | text cross-fades when the latest campaign changes (260 ms); the pulse dot pings three times, then rests. No marquee. | text swaps |
| Proof numerals | no count-up. They are evidence, not decoration. | same |
| Technical details | native `<details>`; content fades in 160 ms | instant |

A final verdict is still never delayed more than 600 ms by animation.

## 7. Check-page simplification, before and after

| v1 (resident sees) | v2 |
|---|---|
| Four tier cards T0–T3 under the hero | removed → `/docs/cascade` |
| "Investigation timeline" side column with tier codes and evidence ids | "The Investigator is checking…" card: four plain steps, one word of state each |
| Evidence ids and hard-rule chips under every reason | reasons are sentences only; ids live in Technical details |
| Risk score bar with "computed by the arbiter" | Technical details |
| Trace steps, check id, tier reached, model route | Technical details |
| "Technical details" toggle inside the timeline | one collapsed row at the foot of the verdict card, linking to `/docs/cascade` |

Unchanged: verdict words and colours, the caution block, actions, the reporting block and its source line, defanged non-clickable URLs, the demo ribbon, every honest error state.

## 8. Honesty review: copy that depends on a capability

Flags as bundled today (`web/lib/capabilities.generated.json`) and as probed from `scripts/submission/capabilities.py` on this branch:

| Flag | Today | Copy affected | Rule |
|---|---|---|---|
| `investigator` | **false** | `agent.inv.aistep`, `act.step.ai`, `agents.inv.2.*` | shown with the In-progress badge (as in the mockups) until the flag is true |
| `injection_defence` | **false** | `docs.security.*` | badge on the Security card and page |
| `sentinel_agent` | true when probed, **not in the web bundle yet** | `home.sub`, `ticker.label`, `agent.sen.*`, `meet.sen.text`, `act.sentinel` | W2-01 adds the flag to the bundle; a missing flag counts as in progress |
| `rest_api`, `mcp`, `stix` | true when probed, not in the web bundle yet | `/authorities`, `/docs/integration` | same |
| `message_check`, `email_check`, `image_check` | true | kind tabs | badge on a tab only when false |

Open points for L1 (each is a decision, not a blocker for building):

1. **What "the Investigator" names.** `CLAUDE.md` defines the Investigator as the whole check (cascade T0–T3 + arbiter, LLM only for the uncertain band). The capability flag `investigator` covers only the LLM step (T3). This spec follows `CLAUDE.md`: the Investigator is shown Live because link checking is live, and its "AI second look" carries its own In-progress badge everywhere the agent is named, including the hero. If L1 prefers the stricter reading, the fallback is one switch: when `investigator` is false, `act.title` reads "Checking your link…" (`status.checking`, existing) and the Investigator chip shows In progress.
2. **"Two AI agents" in the H1 while `investigator` is false.** The headline names the product's design; the badge beside it states what runs today. If L1 judges that too strong, use the eyebrow as H1 fallback ("AI agents against scams") until the flag flips.
3. **"The Sentinel compares this check with others" (`act.sentinel`)** is a general statement. The verdict contract has no campaign link, so the result page cannot say "this check belongs to campaign X". Proposal for L1 (contract change, not made here): an optional `campaign_id` on the verdict or a `GET /v1/verdicts/{id}/campaign` lookup.
4. **`test.message_path.dangerous_recall` is 0 in the artifact.** Not shown in v2. builder-evals should confirm what the field measures before any page displays the message-path block.
5. **Speed.** The artifact has no latency field. "In seconds" is the product statement in `CLAUDE.md`; no figure is shown. If judges should see one, builder-evals adds `latency_p50_ms` / `latency_p95_ms` to the artifact first.
6. **Sample size.** `test.n` is small and the ranges are wide. The scope line and the range sit beside every headline number on purpose; do not remove them to tidy the layout.

## 9. Rules carried over (checked by the generator and by the tests in the task cards)

- Never "safe" / «آمن»; the lowest verdict is "No warning signs found" with the caution reminder.
- No Abu Dhabi Police logo, colours or look-alike mark; channels come only from `config/reporting_channels.yaml` with source and date; "ready to connect, not connected" on Home, `/authorities` and the footer.
- Every number from the artifact; demo data labelled; nothing asks for personal, banking or ID details.
- Strict CSP unchanged: no inline style attributes in server HTML (the mockups use a few; the app must use classes), no `dangerouslySetInnerHTML`, self-hosted fonts.
