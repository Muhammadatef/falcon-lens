# Falcon Lens pitch deck: design spec (v2, animated)

Status: design only. A builder implements this in `submission/build/build_deck.py` on top of `origin/docs/pitch-final` (PR #150). Outputs stay `submission/FalconLens_ScamShield.pptx` and `submission/FalconLens_ScamShield.pdf`.

Inputs read for this spec: `submission/build/build_deck.py` (13 slides, python-pptx 1.0.2), `submission/DEMO_SCRIPT.md`, `docs/assets/architecture.svg`, `web/design/tokens.css`, `scripts/submission/check_numbers.py`, `scripts/submission/evidence.py`, and the organiser guide (criteria, weights, pitch format: 3 minutes of pitch and demo of which at most 1 minute states the problem and solution, then 2 minutes of questions).

## 0. Constraints that shape every decision

1. **The number tracer reads every `<a:t>` run in slides and notes.** A digit passes only if it is an artifact value, is glued to an ASCII letter (`C1`, `T0`, `p95`), or matches a reviewed context such as `0:55 to 1:00`. A percentage is never exempt. So:
   - No typed digits anywhere. Every figure is interpolated from `Facts` (`f.metric`, `f.fp`, `f.ev`). Do not parse numbers back out of the `*_line()` strings; add small accessors to `scripts/submission/evidence.py` that return the same values the lines use.
   - **No criterion weights as numbers.** Show the weight as a proportional bar (section 2.6).
   - **No slide numbers and no typed agenda numerals.** Agenda numerals come from PowerPoint auto-numbering (`<a:buAutoNum>`), which is a list marker, not text. Criteria are labelled `C1` to `C5`.
   - Do not add a pattern to `ALLOWED_CONTEXTS` for this deck. If one seems necessary, stop and ask L1; that is a change to a truthfulness gate.
2. **The problem slide carries no statistic.** No cited official figure is in the repo, and the tracer would reject one. Use the human story line (section 1, slide 4).
3. **The PDF and the QA screenshots show each slide's final state.** Every slide must be complete and legible with all builds finished. Nothing may overlap, replace or hide another element; there are no exit animations.
4. **Wording.** Never the word for "harmless" in English or Arabic, even negated. The top verdict word is «خطِر». The lowest verdict is "No warning signs found" / «لم نجد علامات تحذير». The independence line is "An independent project. Ready to connect, not connected." No Abu Dhabi Police logo, crest, colours or uniform imagery. Reuse the existing copy strings wherever one exists; `descriptions.wording_errors()` must stay clean.
5. **Capability truth.** Any line about a capability goes through `status(f, cap, text)` or `cap_on(f, cap)`, as today. Nothing is promoted from Planned by this redesign.
6. **Media.** `verify_pptx` allows PNG only and the file limit is 20 MB. The hook video is not embedded by the build; the slide carries a placeholder frame and the owner inserts the file on the presenting machine (slide 3).

## 1. Narrative and slide list (14 slides)

The owner's list is 16 items; the cap is 14. Two merges, chosen so that nothing shown in the three minutes is lost: **Pilot path + Honest limits** share slide 13 (both are question-time slides and both serve criterion 5), and **Team + Close** share slide 14. If L1 prefers separate Limits and Team slides, merge Problem into Solution and Architecture into Solution instead; do not exceed 14.

Seven agenda sections drive a section tracker on every slide from 3 onward (section 2.5).

| # | Key | Slide | Section | In the 3 minutes | Clicks |
|---|---|---|---|---|---|
| 1 | `title` | Title | none | Holding slide before the clock starts | 0 |
| 2 | `agenda` | Agenda | none | Pre-roll, about 5 s while the team is introduced | 1 to leave |
| 3 | `hook` | Hook video, full-bleed | Hook | 0:00 to 0:25 | 1 to leave |
| 4 | `problem` | Problem | Problem | 0:25 to 0:33 | 1 to leave |
| 5 | `solution` | Solution: two agents and the voice | Solution | 0:33 to 0:45 | 1 build, 1 to leave |
| 6 | `architecture` | Architecture in three layers | Solution | 0:45 to 0:55 | 1 build, 1 to leave |
| 7 | `demo` | Live demo beats | Live demo | 0:55 to 1:00, then the browser until 2:40 | 0 |
| 8 | `c_detection` | C1 Detection accuracy | Criteria | Questions only | 1 to leave |
| 9 | `c_early` | C2 Early detection and coverage | Criteria | Questions only | 1 to leave |
| 10 | `c_explain` | C3 Explainability and actionability | Criteria | Questions only | 1 to leave |
| 11 | `c_uae` | C4 UAE relevance and innovation | Criteria | Questions only | 1 to leave |
| 12 | `c_feasible` | C5 Feasibility and presentation | Criteria | Questions only | 1 to leave |
| 13 | `pilot_limits` | Pilot path and honest limits | Pilot path | Questions only | 1 to leave |
| 14 | `close` | Close and team | Team | 2:40 to 3:00 (jump from the browser) | 0 |

Run-sheet consequences for L1 (not the builder's call):
- `DEMO_SCRIPT.md` says "you only show the first four slides and the closing slide". With this order it is slides 1 to 7 and slide 14. `submission/build/demo_template.md` needs that sentence updated; the timings do not change.
- To jump from the browser to the close at 2:40, the presenter types the slide index and Return in slideshow mode, or keeps the deck window on slide 14 in a second space. Put this in the run-sheet's "Before you go on stage".
- The on-screen tagline becomes the owner's «اسأل الصقر قبل لا تضغط». The run-sheet's spoken close still ends «افحص قبل أن تضغط». L1 decides whether the template changes; the deck uses the owner's line on slides 1 and 14.

### Slide content

**1. Title.** Lens mark (the existing `lens()` drawing, large, 1.6 in) left of the wordmark "Falcon Lens | عدسة الصقر". Under it the tagline pair: «اسأل الصقر قبل لا تضغط» (sand) and "Ask the falcon before you tap." (text). One line of promise (existing copy): "An Arabic-first AI that tells UAE residents whether a link, message or email is a scam, with evidence, in seconds." Bottom-left chip: "Independent project · ready to connect, not connected". Bottom-right, faint: "ScamShield AI Hackathon entry". No date digits.

**2. Agenda.** Title "Agenda · جدول العرض". Seven rows, auto-numbered, English left and Arabic right on the same row:

| Row | English | Arabic |
|---|---|---|
| a | Hook | المشهد |
| b | Problem | المشكلة |
| c | Solution | الحل |
| d | Live demo | العرض المباشر |
| e | How we meet the criteria | كيف نستوفي المعايير |
| f | Pilot path | مسار التجربة |
| g | Team | الفريق |

Each row is a group: a numeral cell (a one-paragraph text box whose only content is the English label with `<a:buAutoNum type="arabicPeriod" startAt="N"/>` so the numeral is a list marker), a hairline, and the Arabic label right-aligned. The active-section highlight is a rounded bar (`surface-2` fill, 3 pt `brand` start edge) that sits behind row a. If Keynote drops the auto-number markers, fall back to seven small `brand` dots; never type numerals.

**3. Hook video.** Full-bleed 13.333 x 7.5 in black-navy frame (`bg`), no chrome, no tracker. Centre: a thin `border-strong` 16:9 outline inset 0.35 in, a play triangle in a circle (`brand` outline, 1.1 in), and under it "Hook video · مشهد افتتاحي" in muted text. Top-start corner, always on top in z-order: the chip «تمثيل — Dramatisation» (`warn` on `warn-tint`, `warn-line` border, 16 pt). Bottom, faint, one line: "Invented bank: Falcon Demo Bank. Fictional people. No police logo, uniform or vehicle." The production details move to the notes.
Owner step on the presenting machine only: insert the video cut made from `demo-kit/hook-video/PROMPT.md`, size it to the full slide, set it to start automatically, then select the chip and choose Bring to Front so the label stays over the video from the first frame. The submitted `.pptx` stays without the video (PNG-only rule, size limit).

**4. Problem.** No statistic. One story, two lines, large:
- Arabic (sand, 40 pt, RTL, right): «رسالة واحدة: "حسابك سيُجمَّد". والصفحة المزيّفة وُلدت اليوم، فليست في أي قائمة.»
- English (text, 30 pt): "One text: 'your account will be frozen'. The fake page was born today, so it is on no list."
Under them, one muted line (existing copy): "A blocklist lists a page only after someone reports it." / «القائمة السوداء لا تُدرج الصفحة إلا بعد أن يبلّغ عنها أحد.» Left third: a phone-shaped outline with a single SMS bubble containing only «حسابك سيُجمَّد» and a `TEST FIXTURE` micro-label; no link, no brand, no number.

**5. Solution.** Three elements, nothing else:
- Top centre, the voice pill: microphone glyph, «يا صقر» and "Hey Falcon", `brand` outline.
- Left card, Baseer: `lens()` icon in `brand`; «بصير» 40 pt, "Baseer, the Investigator" 20 pt; one line "Judges one message, link or email." / «يحكم على رسالة أو رابط أو بريد واحد.»
- Right card, Dir': `radar()` icon in `sand`; «درع» 40 pt, "Dir', the Sentinel" 20 pt; one line "Watches around the clock and links checks into campaigns." / «يراقب على مدار الساعة ويربط الفحوص في حملات.»
- Bottom strip, second beat: "Fixed code sets the score, not the AI. Outside actions wait for a human." and the three verdict plates from the existing `verdict_row()` (strings from `packages/falcon_core/i18n/ar.yaml`), top plate «خطِر».

**6. Architecture.** Drawn natively (not the PNG) so each layer can animate. Three full-width bands, top to bottom on the slide: Voice, Two agents, Platform. Each band: a heading at the start edge (English caps 13 pt `brand` + Arabic 14 pt `sand`) and a row of node chips. Text is taken from `docs/assets/architecture.svg`; do not add components that are not in it.
- Voice · طبقة المساعد الصوتي: mic · speech to text, local · wake phrase «يا صقر» · intent · action · narration.
- Two agents · طبقة الوكيلين الذكيين: two sub-rows. «بصير» Baseer: T0 · T1 · T2 · T3 · deterministic arbiter. «درع» Dir': listens · correlates · rules decide · LangGraph triage · human approval.
- Platform · المنصة: REST and SSE API · event bus · Postgres with pgvector · isolated sandbox and egress proxy · MCP, STIX, webhooks (chip suffix "ready to connect, not connected") · observability.
- Flow overlay (second beat): a vertical `brand` beam, 3 pt, with an arrowhead, down the start-side gutter from the Voice band to the Platform band, and three small `brand` pulse dots where it crosses each band. Caption at the bottom: "A request flows down: the voice layer calls the same public check API." / «الطلب ينزل من الأعلى إلى الأسفل.»
- Footer, faint: "Model route chosen by an operator: cloud with local fallback, or local only."

**7. Live demo.** A horizontal rail with six stops, times from the run-sheet table in `DEMO_SCRIPT.md` in the exact form `0:55 to 1:00` (the tracer allows only that form). Each stop: time (brand, 14 pt), beat name (bold 17 pt), one line (muted 13 pt). Take the beat text from the run-sheet, not from the old slide (the old slide's times differ from the run-sheet and it says the falcon "speaks the real findings", which the run-sheet marks Planned). Stops: switch to the browser · Arabic voice check «يا صقر، شيّك اللي نسخته» to «خطِر» · English question · trace in /history · campaigns and results · route selector in /ops. Evidence-pack and voice-findings wording goes through `status()`. Footer: "Live on our own machine. Demo data is labelled. Fallback: the paste box, and localhost."

**8 to 12. One slide per criterion.** Same template (section 2.6). Left: the `C#` chip, the organiser's criterion name in English and Arabic, the weight bar, then the hero figure with label and source line. Right: three "how we meet it" rows and one amber "read this with it" row that states the limit of the hero figure. Hero and counterweight values, all from published artifacts through `Facts`:

| Slide | Arabic title (organiser wording) | Hero figure | Hero label | Supporting figures | Amber counterweight row |
|---|---|---|---|---|---|
| C1 Detection accuracy | دقّة الكشف | `pct(f.metric("test.recall"))` | "of phishing links caught · frozen test split, address only" | `pct(f.metric("test.fpr"))` false-alarm rate; `f.metric("test.official_false_dangerous")` official sites marked Dangerous; `f.ev.fresh_second_line()` | Live full stack: `pct(f.fp["false_positive_rate"]["value"])` of `f.fp["n"]` held-out legitimate sites flagged, target `pct(f.fp["target"])`. Above target; first fix. |
| C2 Early detection and coverage | الكشف المبكر والتغطية | `k of n` from `f.ev.brand_new["groups"]["new_lookalike_brand_pages"]` (`dangerous_final.k`, `n`) | "brand-new look-alike pages flagged Dangerous · synthetic, hosts in no feed" | `f.ev.message_line()`; hunter and helpline rows through `status()` | Benign controls warned `k of n` (`benign_controls_novel_hosts.warning_final`). Search, ads and Maps: "Ready, needs a key"; no result shown. |
| C3 Explainability and actionability | قابلية التفسير والتنفيذ | `k of n` from `f.ev.faith[...]["reasons_faithful"]` (the values `faith_line()` uses) | "shown reasons cite evidence in the verdict · fixture verdicts" | `f.ev.t3_line()`; trace in /history; export row "REST, signed webhooks, MCP, STIX: ready to connect, not connected" | Evidence pack through `status(f, "evidence_pack", ...)`. Reasons are templates, not model text. |
| C4 UAE relevance and innovation | الارتباط بدولة الإمارات والابتكار | the wake-phrase figure that `f.ev.voice_line()` formats | "wake phrase recognised · synthetic speech" | the other `voice_line()` figures; `f.ev.voice_speed()`; brand registry row; campaigns and perceptual hash row | "Synthetic speech and noise, not real speakers: an upper bound. A native reader's rating of the Arabic is not measured yet." |
| C5 Feasibility and presentation | الجدوى والعرض التقديمي | cloud-model calls in sovereign mode: `run["egress_audit"]["anthropic_sink_hits"]` | "calls to a cloud model in sovereign mode · one machine" | scenarios passed per local model from `run["scenario_counts"]` (as in `sovereign_line()`); "Scales by adding workers; proven on one machine only" | "One of the runs is marked failed: the Sentinel summary fell back to a template. Lookups about the checked site still use the internet through the egress proxy." |

If an artifact family is missing, the slide shows "Not measured yet" in place of the hero figure in `faint`, never a blank and never a typed value. The C1 notes sentence about the batch checker must be gated by `cap_on(f, "batch_check")`.

**13. Pilot path and honest limits.** Two rows.
- Top row, "Pilot path · مسار التجربة": four connected steps on a rail: "On-premise install" (same stack inside the authority's network) · "Shadow mode" (verdicts recorded, nothing sent) · "Analyst review" (their sign-on, feeds, security review) · "Connect" (REST, MCP, STIX: ready to connect, not connected). The last node is outlined, not filled, to show it has not happened.
- Bottom row, "Honest limits · حدودنا بصراحة", `warn` accents, three cards built from the existing `slide_limits()` items: live false alarms above target (values from `f.fp`); the fresh test is one run (`f.ev.fresh_caveat()`) and voice, red-team, message and look-alike sets are synthetic; not measured yet (native Arabic rating, sandbox recall on labelled phishing pages).

**14. Close and team.** Centre, hero: «اسأل الصقر قبل لا تضغط» (brand, 54 pt) and under it "Ask the falcon before you tap." (sand, 28 pt). Middle: five small recap chips, one per criterion, text from the existing `slide_close()` recap. Lower band: "Team · الفريق" and three names only, equal weight, 20 pt: Mohamed Atef (Leader) · Abdulrahman Alseiari · MokhmadSalakh Salamov. Footer: repository URL (`f.repo_url`) at the start edge; at the end edge the dashed chip "An independent project. Ready to connect, not connected. Not affiliated with Abu Dhabi Police." No roles beyond "(Leader)", no photos, no emails.

## 2. Visual system

### 2.1 Canvas and grid
- 16:9, 13.333 x 7.5 in (`W`, `H` as today). Margins 0.6 in left and right (`MARGIN`), 0.3 in top, 0.35 in bottom.
- Twelve columns across 12.133 in: column 0.85 in, gutter 0.176 in. Use spans of 5 + 7 (criterion slides), 6 + 6 (solution), 4 + 8 (problem), 12 (architecture, demo, agenda).
- Vertical bands: chrome 0.30 to 0.76; title 0.90 to 1.65; content 1.85 to 6.75; tracker 6.95 to 7.20.
- Spacing steps 0.1, 0.2, 0.3, 0.6 in. Card radius 0.12 in; card fill `surface-1`, hairline `border`; raised or active fill `surface-2`.
- At most about 40 words of body copy on a slide shown in the three minutes; criterion slides may carry more because they are read during questions.

### 2.2 Colour (night theme of `web/design/tokens.css`, already in `C`)
| Role | Token | Hex |
|---|---|---|
| Slide background | `--fl-bg` | 070b14 |
| Card / raised / pressed | `--fl-surface-1/2/3` | 0e1626 / 16203a / 1f2c4c |
| Hairline / strong outline | `--fl-border` / `--fl-border-strong` | 2a3757 / 5a6c92 |
| Text / muted / faint | `--fl-text` / `-muted` / `-faint` | f2eee6 / aeb8cc / 8794ae |
| Brand (lens, active, hero figures) | `--fl-brand` | 3fe0c5 |
| Warm accent (Arabic titles, Dir') | `--fl-sand` | e7d7b6 |
| Dangerous | fg ff8589, solid d42a38, tint 2b0f15, line 8c2630 |
| Suspicious / caveats | fg ffc55c, tint 2a1d07, line 8a6416 |
| No warning signs found | fg a9c0ff, solid 3a5bd0, tint 111c3d, line 34488c |

Add `border_strong` (5a6c92), `nws_solid` (3a5bd0) and `warn_solid` (f4b23a) to `C`. **No green anywhere**; green reads as the word the product never says. Brand teal is used for identity and for figures, never as a verdict colour. Amber is reserved for caveats and Planned items. Red appears only on the Dangerous plate.

### 2.3 Typography
- `.pptx`: **Arial** for Latin and Arabic (`PPTX_FONT`, set on `a:latin` and `a:cs`, as `set_font()` does). It ships with macOS, Windows, PowerPoint and Keynote, covers Arabic, and gives no missing-font sheet. The PDF keeps Readex Pro. Do not introduce a second face.
- Scale (pt): hero figure 96 bold · display 54 bold · slide title English 34 bold, Arabic 30 bold · heading 22 bold · body 18 to 20 · secondary 15 to 16 · source and footer lines 12. Nothing under 12; nothing under 15 on slides 1 to 7 and 14.
- Arabic blocks: `rtl="1"`, right-aligned, `lang="ar-AE"`, set one size step larger than the paired English and with 1.25 line spacing (Arabic marks need room); English 1.1. Arabic is written first or placed at the reading-start (right) side when both share a row; on two-language title rows English sits left, Arabic right, as today.
- Numerals are Western digits, left-to-right, including inside Arabic lines. Use the guillemets « » for Arabic quotations.
- Sentence case. No all-caps except the 13 pt layer headings on the architecture slide.

### 2.4 Icons and shapes
- Line icons only, 2 pt stroke, round caps, built from native shapes (as `lens()` and `radar()` are): lens = Baseer, radar = Dir', microphone = voice, layers = platform, person-with-tick = human approval. No emoji, no stock art, no third-party logos, no real brand marks. The falcon appears only as the product's own mark from `web/public/icons/icon-512.png` if used at all.
- Verdict plates: colour, shape and word always together (DESIGN.md section 4). Use the shapes that file defines; if it defines none: octagon for «خطِر», triangle for Suspicious, circle for No warning signs found.
- Chips: pill, 1 pt line, tint fill, 13 to 16 pt text. Planned items: dashed `warn-line` outline and the word "Planned" first.

### 2.5 Chrome and the section tracker
- Slides 4 to 14 keep the existing `frame()`: 0.07 in brand rule at the top, lens mark, wordmark, the independence line at the top end edge, bilingual title. Slide 1 and slide 3 have no frame; slide 2 has the frame without a tracker.
- **Section tracker** (the agenda highlight reused as the section divider): at y 7.02, seven segments across the content width, each 1.665 in wide, 0.05 in tall, 0.08 in apart. Past sections `border-strong`, the active section `brand` at 0.09 in tall, coming sections `border`. Above the active segment, 12 pt: the section name in English and Arabic (`faint`). No numerals. Static on every slide except where section 3 says it animates.

### 2.6 How numbers are shown
- **Hero figure block** (criterion slides, left span): figure 96 pt bold `brand`, left-aligned, LTR. Directly under it a 0.06 in meter: a `border` track 4.6 in wide and a `brand` fill whose width is value x track for a rate, or `k/n` x track for a count. Then the label, 18 pt `text`, one or two lines stating what was measured and on what. Then the source line, 12 pt `faint`: "Source: evals/results/published/<family>/<file stem>" (use the names the tracer already accepts; if it flags a bare timestamp stem, cite the family folder only).
- A figure never appears without its denominator or scope ("12 of 12 · synthetic", "frozen test split, address only"), and a red-team harmful count never without the answered count.
- Supporting figures: 28 pt bold `text` with a 14 pt muted label, at most three per slide.
- The amber counterweight row sits level with the hero figure, `warn` 2 pt start edge on `warn-tint`, 15 pt. It is part of the slide's first build, not a click the presenter can skip.
- **Weight bar** (replaces the forbidden weight percentages): five segments on one 4.6 in bar, widths in the organiser's proportions 6 : 5 : 4 : 3 : 2, the current criterion's segment `sand`, the others `border`. The proportions are geometry constants in code, never text. Caption 12 pt faint: "Share of the judging score".
- Synthetic, replay and fixture data carry a chip saying so, on the slide, next to the figure.

## 3. Motion

Principles: motion explains order (what to read first) and structure (layers, flow). Entrances only; no exits, no emphasis effects, no motion paths, no loops, no sound. Each element takes at most 1.2 s (most take 0.3 to 0.6 s). One click equals one spoken beat; everything inside a beat chains with After Previous or With Previous. A slide that is jumped to during questions finishes building within about 2.5 s without a click.

### 3.1 Vocabulary (the only effects allowed)

| Name in this spec | PowerPoint entrance | `presetID` / `presetSubtype` | Behaviour nodes | Expected Keynote import |
|---|---|---|---|---|
| `fade` | Fade | 10 / 0 | `set style.visibility` + `animEffect filter="fade"` | Dissolve |
| `wipe_from_left` | Wipe, From Left | 22 / 8 | `animEffect filter="wipe(left)"` | Wipe |
| `wipe_from_right` | Wipe, From Right | 22 / 2 | `animEffect filter="wipe(right)"` | Wipe |
| `wipe_from_top` | Wipe, From Top | 22 / 1 | `animEffect filter="wipe(up)"` | Wipe |
| `wipe_from_bottom` | Wipe, From Bottom | 22 / 4 | `animEffect filter="wipe(down)"` | Wipe |
| `zoom` | Zoom, In | 53 / 16 | `anim ppt_w`, `anim ppt_h` from 0 + fade | Scale |
| `fly_from_bottom` | Fly In, From Bottom | 2 / 4 | `anim ppt_x`, `anim ppt_y` | Move In |

Arabic blocks wipe from the right (their reading start); English and mixed rows wipe from the left. `fly_from_bottom` is in the vocabulary as a fallback only: if a wipe on a group renders badly in Keynote, replace that step with `fade`, not with a fly-in. The Keynote column is the expected mapping and is **unverified** until the acceptance run; if Keynote drops an effect, the element is simply visible from the start, which is acceptable because every slide's final state is complete.

### 3.2 Slide transitions

| Into slide | Transition | Duration | Advance |
|---|---|---|---|
| 1 | none (first slide) | | click |
| 2, 4, 5, 6, 7, 13, 14 | Fade (`<p:fade/>`) | 0.6 s | click |
| 3 (hook) | Fade | 0.4 s | click, after the video ends |
| 8 (first criterion) | Fade | 0.6 s | click |
| 9 to 12 (criterion to criterion) | Push from the right (`<p:push dir="l"/>`) | 0.6 s | click |

No automatic slide advance anywhere. **No Morph**: it needs PowerPoint 2019 or later, depends on matched object names, and Keynote ignores it; nothing in this deck needs it. Emit each transition as PowerPoint itself does, inside `mc:AlternateContent` with `p14:dur` in the Choice and a plain `<p:transition spd="med">` in the Fallback (Appendix A does this). If Keynote or LibreOffice mishandles the wrapper, emit only the plain Fallback form; the duration then becomes PowerPoint's medium speed, which is acceptable.

### 3.3 Choreography per slide

Columns: trigger `auto` = starts when the slide appears (After Previous with no click), `click`, `after` = After Previous, `with` = With Previous. Delay and duration in milliseconds. Targets are named groups; a card and its text are one group so that one effect moves both.

**Slide 1, Title** (auto, about 2.3 s)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | lens mark | zoom | auto | 200 | 500 |
| 2 | wordmark | fade | after | 0 | 500 |
| 3 | Arabic tagline | wipe_from_right | after | 0 | 500 |
| 4 | English tagline | fade | with | 150 | 400 |
| 5 | promise line | fade | after | 0 | 400 |
| 6 | independence chip | fade | after | 100 | 300 |

**Slide 2, Agenda** (auto, about 3.5 s; items appear one by one, then the active-section highlight)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 to 7 | rows a to g, in order | wipe_from_left | auto for row a, then after | 70 | 350 |
| 8 | highlight bar behind row a | fade | after | 200 | 400 |

The highlight bar is drawn under row a in z-order and animates last, so the eye lands on "Hook", which is the next slide. The same bar style is the active segment of the section tracker on every later slide.

**Slide 3, Hook video.** No element animation. The video plays automatically once the owner has inserted it.

**Slide 4, Problem** (auto, about 2.9 s)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | phone outline | fade | auto | 150 | 400 |
| 2 | SMS bubble | zoom | after | 200 | 400 |
| 3 | Arabic story line | wipe_from_right | after | 100 | 600 |
| 4 | English story line | fade | after | 0 | 500 |
| 5 | blocklist line (both languages) | fade | after | 300 | 400 |

**Slide 5, Solution** (beat 1 auto, beat 2 on click)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | voice pill «يا صقر» | zoom | auto | 150 | 450 |
| 2 | Baseer card | wipe_from_bottom | after | 0 | 500 |
| 3 | Dir' card | wipe_from_bottom | with | 150 | 500 |
| 4 | "Fixed code sets the score" line | fade | click | 0 | 400 |
| 5 | plate «خطِر» | fade | after | 80 | 300 |
| 6 | plate Suspicious | fade | after | 80 | 300 |
| 7 | plate No warning signs found | fade | after | 80 | 300 |

**Slide 6, Architecture** (beat 1 auto: three layers build bottom-up; beat 2 on click: the request flows down)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | Platform band (bottom) | wipe_from_bottom | auto | 150 | 600 |
| 2 | Two-agents band (middle) | wipe_from_bottom | after | 150 | 600 |
| 3 | Voice band (top) | wipe_from_bottom | after | 150 | 600 |
| 4 | flow beam, top to bottom | wipe_from_top | click | 0 | 900 |
| 5 | pulse dot on the Voice band | fade | with | 0 | 250 |
| 6 | pulse dot on the agents band | fade | with | 350 | 250 |
| 7 | pulse dot on the Platform band | fade | with | 700 | 250 |
| 8 | flow caption | fade | after | 0 | 400 |

The beam and dots are extra shapes drawn above the bands; they are the "highlight". Do not recolour the bands.

**Slide 7, Live demo** (auto, about 1.4 s; the presenter leaves for the browser within five seconds)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | rail line | wipe_from_left | auto | 100 | 700 |
| 2 to 7 | stops one to six | fade | with | 100, 210, 320, 430, 540, 650 | 300 |
| 8 | footer line | fade | after | 0 | 300 |

**Slides 8 to 12, criterion template** (auto, about 2.0 s; the count-up feel)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | weight bar | wipe_from_left | auto | 100 | 300 |
| 2 | hero figure | wipe_from_bottom | after | 0 | 550 |
| 3 | meter fill | wipe_from_left | with | 150 | 800 |
| 4 | hero label | fade | after | 0 | 300 |
| 5 | source line | fade | with | 100 | 300 |
| 6 | amber counterweight row | fade | with | 250 | 400 |
| 7 to 9 | the three "how" rows | fade | with | 150, 230, 310 | 300 |

The count-up feel comes from the figure rolling up from its baseline while the meter fills to the measured proportion. **Do not animate through intermediate digits** (stacked text boxes showing other values): those would be numbers that no artifact contains. The counterweight row is in the same automatic sequence as the hero figure so that the figure is never on screen for long without its limit.

**Slide 13, Pilot path and honest limits** (auto, about 2.6 s)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | pilot rail | wipe_from_left | auto | 100 | 600 |
| 2 to 5 | the four pilot steps | fade | with | 0, 150, 300, 450 | 300 |
| 6 to 8 | the three limit cards | fade | after | 80 | 350 |

**Slide 14, Close and team** (auto, about 2.2 s)
| # | Target | Effect | Trigger | Delay | Dur |
|---|---|---|---|---|---|
| 1 | Arabic tagline | zoom | auto | 200 | 600 |
| 2 | English tagline | fade | after | 100 | 400 |
| 3 to 7 | five recap chips | fade | after for the first, then with | 0, 70, 140, 210, 280 | 300 |
| 8 | team row | fade | after | 200 | 400 |

Minimum entrance effects per slide, for the acceptance count: 6, 8, 0, 5, 7, 8, 8, 9, 9, 9, 9, 9, 8, 8. Total 103.

### 3.4 Implementation in PPTX XML

- Extend the drawing model: a `Group(name, shapes)` (written with `slide.shapes.add_group_shape()`; flattened by the HTML writer) and a `Slide.motion: list[Step]` plus `Slide.transition`. A `Step` names its target; resolve names to shape ids (`shape.shape_id`) after all shapes are written.
- In `<p:sld>` the schema order is `cSld`, `clrMapOvr`, `transition`, `timing`, `extLst`. Insert in that order.
- Timing tree: `tmRoot` par, one `mainSeq` seq, then one par per click beat whose start condition is `delay="indefinite"`. A beat that must start without a click also carries `<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>` and its first effect has `nodeType="afterEffect"`. Inside a beat, each After Previous step opens a new time-slot par whose `delay` is the accumulated end time of the earlier slots; With Previous steps join the current slot with their own delay. `cTn` ids are unique per slide, starting at 1.
- Every entrance begins with `<p:set>` on `style.visibility` to `visible`; that is what hides the shape before its turn.
- `<p:bldLst>`: one `<p:bldP spid grpId="0" animBg="1"/>` for each animated `p:sp` that has a text body. No entry for pictures or groups.
- Animate whole shapes or groups only (`<p:spTgt spid>`), never paragraph ranges; paragraph builds import poorly into Keynote.
- Appendix A is a reference injector for all of the above. It produces well-formed XML that python-pptx 1.0.2 re-opens, with the correct child order, and macOS Quick Look renders the result. Playback in PowerPoint and import into Keynote were **not verified** when this spec was written; the builder verifies them (section 5).
- The HTML and PDF path ignores motion and renders the final state.

## 4. Speaker notes

Rules for every notes block:
- Format, in this order: `SAY (EN):` the spoken English line. `SAY (AR):` the spoken Arabic line. `DO:` clicks and cues. `IF IT FAILS:` the fallback, where one exists. `Q&A:` likely questions, on slides 8 to 13 only.
- The spoken lines for slides 3, 5, 7 and 14 are the lines of `DEMO_SCRIPT.md`, word for word. Do not paraphrase the run-sheet.
- Notes are scanned by the tracer and the wording check. No typed digits: interpolate values from `Facts`, or point at the slide ("the figure on the slide"). Never the word for "harmless". Always "ready to connect, not connected". Always the answered count with a red-team count.
- Each slide that is shown in the three minutes has at most about twenty-five spoken words per language per ten seconds.

| Slide | SAY (EN) | SAY (AR) | DO / IF IT FAILS |
|---|---|---|---|
| 1 Title | Keep the existing title note: who we are, a real check on our own machine, two agents, independent, ready to connect and not connected. | «نحن فريق «عدسة الصقر». سترون فحصاً حقيقياً على جهازنا، بالعربية وبالصوت. مشروع مستقل: جاهز للربط وغير مربوط.» | Holding slide. Click when invited to start. |
| 2 Agenda | "Our path: a short scene, the problem, our solution, a live demo, how we meet your criteria, the pilot path, and the team." | «مسار العرض: مشهد قصير، ثم المشكلة والحل، ثم عرض مباشر، ثم كيف نستوفي معاييركم، ومسار التجربة، والفريق.» | Builds by itself. Click to the hook; the clock starts there. |
| 3 Hook | Nothing over the video. Then pause one second. | Nothing over the video. | The video starts by itself. IF IT FAILS: the Abu Saeed line from the run-sheet, in Arabic then English, and click on. Note also the production facts moved off the slide: invented bank, fictional people, no police logo, uniform or vehicle. |
| 4 Problem | "A blocklist lists a scam page only after somebody reports it, so a page that is new today is on no list today, and the warning is rarely in the language people read." | «القائمة السوداء لا تُدرج الصفحة إلا بعد أن يبلّغ عنها أحد، فالصفحة الجديدة اليوم ليست في أي قائمة.» | Builds by itself. One click to the solution. |
| 5 Solution | The run-sheet solution lines, from "Falcon Lens is two AI agents" to "Hey Falcon". | The run-sheet Arabic lines, from «عدسة الصقر وكيلان بالذكاء الاصطناعي» to «يا صقر». | Click once at "fixed code, not the AI, sets the score" to bring in the verdict plates. |
| 6 Architecture | "Three layers. The platform at the bottom, the two agents in the middle, your voice on top. A request flows down, and it can all run sovereign, on local models, on this machine." | «ثلاث طبقات: المنصة في الأسفل، والوكيلان في الوسط، وصوتك في الأعلى. الطلب ينزل من الأعلى، وكل ذلك يعمل محلياً على هذا الجهاز.» | Layers build by themselves. Click once at "a request flows down". If time is short, skip this slide; say the last sentence over slide 5. |
| 7 Live demo | "This is live, on our machine." | «هذا عرض مباشر على جهازنا.» | Switch to the browser at once. The beat-by-beat lines are in the run-sheet table. IF IT FAILS: the run-sheet's failure table (paste box, localhost, the criterion slides). |
| 8 C1 | Keep the existing detection note, with the batch sentence gated by `cap_on(f, "batch_check")`. | «المعيار الأول، دقّة الكشف: الدرجة يحدّدها محكّم ثابت لا نموذج لغوي، والأرقام أمامكم مع حدودها.» | Q&A: hidden set, false alarms on banks, redirects and cloaking (run-sheet answers). |
| 9 C2 | Keep the existing early-detection note. | «المعيار الثاني، الكشف المبكر: نلتقط الصفحة المنتحِلة حتى إن لم تُدرج في أي قائمة، ونعرض الصفحات المشروعة للمقارنة بجانبها.» | Q&A: search, ads and Maps ("Ready, needs a key"); brand-new look-alikes. |
| 10 C3 | Keep the existing explainability note. | «المعيار الثالث، التفسير: لكل حكم أسبابه وأثره، ولا يخرج أي إجراء إلا بموافقة إنسان.» | Q&A: does an LLM decide the verdict. |
| 11 C4 | Keep the existing UAE note. | «المعيار الرابع: عربي أولاً، وعلامات إماراتية، وتخاطبه بصوتك: يا صقر. أرقام الصوت من كلام مُولَّد، فهي حدّ أعلى.» | |
| 12 C5 | Keep the existing feasibility note. | «المعيار الخامس: عرض حي على جهازنا، ويعمل محلياً بالكامل، ومسار تجريبي داخل شبكتكم. جاهز للربط وغير مربوط.» | Q&A: sovereignty, scale. |
| 13 Pilot and limits | Join the existing limits note and the pilot sentence of the next-thirty-days note. | «مسار التجربة: المنظومة نفسها داخل شبكتكم، في وضع المراقبة أولاً. وحدودنا نقولها نحن: الإنذارات الخاطئة في التشغيل الحي أعلى من هدفنا، وهي أول ما نصلحه.» | Q&A: what a pilot looks like; what the limits are. |
| 14 Close and team | The run-sheet close, then: "Ask the falcon before you tap. We are Mohamed Atef, Abdulrahman Alseiari and MokhmadSalakh Salamov. Thank you." | The run-sheet Arabic close, ending «اسأل الصقر قبل لا تضغط. شكراً لكم.» | Jump here from the browser with twenty seconds left. Stay on this slide for questions. |

## 5. Acceptance checklist for the builder

Build and gates
- [ ] `uv run --with-requirements scripts/submission/requirements.txt python submission/build/build_deck.py --qa-dir submission/build/.cache/qa` exits 0 and writes `submission/FalconLens_ScamShield.pptx` and `submission/FalconLens_ScamShield.pdf`, each under 20 MB.
- [ ] `make submission` exits 0: the number tracer and the wording check pass on slides and notes. No new `ALLOWED_CONTEXTS` entry, no change to `check_numbers.py` or `descriptions.py`.
- [ ] `submission/build/check.py` still passes.
- [ ] Exactly 14 slides, every one with notes in the section 4 format.

Package validity (extend `verify_pptx`)
- [ ] Every `.xml` and `.rels` part in the package parses with lxml.
- [ ] `ppt/presentation.xml` contains `<p:notesMasterIdLst>` (the Keynote fix in `register_notes_master`).
- [ ] Media are PNG only; no macros, no SmartArt, no embedded video or audio.
- [ ] Each slide's children are in schema order: `cSld`, `clrMapOvr`, transition (or its `mc:AlternateContent`), `timing`.
- [ ] Slides 2 to 14 each have a transition; slide 1 has none.
- [ ] Count `presetClass="entr"` per slide: at least 6, 8, 0, 5, 7, 8, 8, 9, 9, 9, 9, 9, 8, 8; at least 100 in total. No `presetClass` other than `entr`. No `repeatCount`, no `autoRev`.
- [ ] No effect duration over 1200 ms. No `advTm` (automatic advance) on any transition.
- [ ] Every `<p:spTgt spid>` refers to a shape id that exists on that slide; `cTn` ids are unique within a slide; every animated text shape has a `bldP`.
- [ ] Click beats per slide (pars with `delay="indefinite"` and no `onBegin` condition): 0 on slides 1 to 4, 7 to 14; 1 on slides 5 and 6.

Rendering
- [ ] The `--qa-dir` PNGs (Chromium) show all 14 slides in their final state with no overflow, no overlap and no clipped Arabic.
- [ ] `qlmanage -t -s 1600 -o <dir> submission/FalconLens_ScamShield.pptx` produces a thumbnail (Quick Look shows the first slide only).
- [ ] If LibreOffice is installed (`soffice --headless --convert-to pdf`), the converted PDF has 14 pages. It is not installed on the build Mac today; if it stays absent, write "LibreOffice render: not run" in the PR, do not claim it.
- [ ] Keynote: the file opens with no repair or missing-font sheet; play slides 1, 2, 5, 6 and 8 and confirm builds run in order with one click per beat. Record what Keynote mapped or dropped.
- [ ] PowerPoint (Mac or Windows): the file opens with no repair prompt; the Animation Pane on slides 2, 6 and 8 shows the sequences of section 3.3. PowerPoint is not installed on the build Mac; if no machine has it, report "PowerPoint playback: unverified" to L1 and the owner. Do not mark it done.

Content
- [ ] No digit in any slide or note was typed; `git grep -nE '"[^"]*[0-9]+%' submission/build/build_deck.py` finds nothing new.
- [ ] No weight percentages, no slide numbers, no typed agenda numerals.
- [ ] The words for "harmless" appear nowhere; «خطِر» is the top verdict word; "ready to connect, not connected" is on slides 1, 13 and 14; no police logo or branding; no real brand, link or phone number.
- [ ] Synthetic, fixture and replay figures carry their label on the slide. Every hero figure has its scope, its source line and its amber counterweight row.
- [ ] Planned capabilities read "Planned" on the slide exactly when `caps` says they are not on main.
- [ ] Team shows names only: Mohamed Atef (Leader), Abdulrahman Alseiari, MokhmadSalakh Salamov.
- [ ] Slide 3 has the «تمثيل — Dramatisation» chip on top of the placeholder frame.

Hand-back to L1
- [ ] Report the three run-sheet items of section 1 (the "first four slides" sentence, the jump to slide 14, the tagline) so L1 can update `submission/build/demo_template.md`.
- [ ] Report anything in this spec that could not be implemented as written, with the fallback used.

## Appendix A. Reference motion injector

Tested at spec time only for: well-formed XML, python-pptx 1.0.2 re-open, child order in `<p:sld>`, Quick Look render. Not yet played in PowerPoint or Keynote.

```python
"""Reference motion injector for DECK_DESIGN.md (python-pptx 1.0.x + lxml)."""
from __future__ import annotations
from dataclasses import dataclass
from lxml import etree

NS_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
NS_P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"

# name: (presetID, presetSubtype, animEffect filter or None)
EFFECTS = {
    "fade": (10, 0, "fade"),
    "wipe_from_left": (22, 8, "wipe(left)"),
    "wipe_from_right": (22, 2, "wipe(right)"),
    "wipe_from_top": (22, 1, "wipe(up)"),
    "wipe_from_bottom": (22, 4, "wipe(down)"),
    "zoom": (53, 16, "fade"),
    "fly_from_bottom": (2, 4, None),
}


@dataclass
class Step:
    spid: int
    effect: str = "fade"
    trigger: str = "after"  # click | after | with
    delay: int = 0  # ms, relative to the trigger
    dur: int = 500  # ms


def transition_xml(kind: str = "fade", dur_ms: int = 600) -> str:
    inner = {"fade": "<p:fade/>", "push_up": '<p:push dir="u"/>', "cut": "<p:cut/>"}[kind]
    return (
        f'<mc:AlternateContent xmlns:mc="{NS_MC}" xmlns:p="{NS_P}">'
        f'<mc:Choice xmlns:p14="{NS_P14}" Requires="p14"><p:transition spd="med" p14:dur="{dur_ms}">{inner}</p:transition></mc:Choice>'
        f'<mc:Fallback><p:transition spd="med">{inner}</p:transition></mc:Fallback>'
        f"</mc:AlternateContent>"
    )


def _effect(step: Step, node_type: str, ids) -> str:
    preset, subtype, filt = EFFECTS[step.effect]
    tgt = f'<p:tgtEl><p:spTgt spid="{step.spid}"/></p:tgtEl>'
    kids = (
        f'<p:set><p:cBhvr><p:cTn id="{next(ids)}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
        f"{tgt}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>"
        f'<p:to><p:strVal val="visible"/></p:to></p:set>'
    )

    def anim(attr: str, start: str, end: str) -> str:
        return (
            f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{next(ids)}" dur="{step.dur}" decel="100000" fill="hold"/>'
            f"{tgt}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr>"
            f'<p:tavLst><p:tav tm="0"><p:val><p:strVal val="{start}"/></p:val></p:tav>'
            f'<p:tav tm="100000"><p:val><p:strVal val="{end}"/></p:val></p:tav></p:tavLst></p:anim>'
        )

    if step.effect == "zoom":
        kids += anim("ppt_w", "0", "#ppt_w") + anim("ppt_h", "0", "#ppt_h")
    if step.effect == "fly_from_bottom":
        kids += anim("ppt_x", "#ppt_x", "#ppt_x") + anim("ppt_y", "1+#ppt_h/2", "#ppt_y")
    if filt:
        kids += f'<p:animEffect transition="in" filter="{filt}"><p:cBhvr><p:cTn id="{next(ids)}" dur="{step.dur}"/>{tgt}</p:cBhvr></p:animEffect>'
    return (
        f'<p:par><p:cTn id="{next(ids)}" presetID="{preset}" presetClass="entr" presetSubtype="{subtype}" fill="hold" grpId="0" nodeType="{node_type}">'
        f'<p:stCondLst><p:cond delay="{step.delay}"/></p:stCondLst><p:childTnLst>{kids}</p:childTnLst></p:cTn></p:par>'
    )


def timing_xml(steps: list[Step], text_spids: set[int]) -> str:
    """steps in play order. 'click' opens a beat; 'after' chains; 'with' runs alongside the previous step."""
    ids = iter(range(3, 100000))
    beats: list[list[list[Step]]] = []  # beat -> slots -> steps
    for st in steps:
        if st.trigger == "click" or not beats:
            beats.append([[st]])
        elif st.trigger == "after":
            beats[-1].append([st])
        else:
            beats[-1][-1].append(st)
    out = ""
    for beat in beats:
        auto = beat[0][0].trigger != "click"
        offset, slots = 0, ""
        for slot in beat:
            body = ""
            for i, st in enumerate(slot):
                node = ("afterEffect" if auto or slot is not beat[0] else "clickEffect") if i == 0 else "withEffect"
                body += _effect(st, node, ids)
            slots += f'<p:par><p:cTn id="{next(ids)}" fill="hold"><p:stCondLst><p:cond delay="{offset}"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst></p:cTn></p:par>'
            offset += max(s.delay + s.dur for s in slot)
        begin = '<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>' if auto else ""
        out += f'<p:par><p:cTn id="{next(ids)}" fill="hold"><p:stCondLst><p:cond delay="indefinite"/>{begin}</p:stCondLst><p:childTnLst>{slots}</p:childTnLst></p:cTn></p:par>'
    bld = "".join(f'<p:bldP spid="{s}" grpId="0" animBg="1"/>' for s in dict.fromkeys(st.spid for st in steps) if s in text_spids)
    return (
        f'<p:timing xmlns:p="{NS_P}"><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
        f'<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>{out}</p:childTnLst></p:cTn>'
        f'<p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        f'<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
        f"</p:childTnLst></p:cTn></p:par></p:tnLst>" + (f"<p:bldLst>{bld}</p:bldLst>" if bld else "") + "</p:timing>"
    )


def apply_motion(slide, steps: list[Step], transition: str = "fade", dur_ms: int = 600) -> None:
    """Call after every shape is on the slide. Schema order in p:sld: cSld, clrMapOvr, transition, timing, extLst."""
    sld = slide._element
    for old in [c for c in sld if c.tag in (f"{{{NS_P}}}transition", f"{{{NS_P}}}timing", f"{{{NS_MC}}}AlternateContent")]:
        sld.remove(old)
    ext = sld.find(f"{{{NS_P}}}extLst")
    parts = [etree.fromstring(transition_xml(transition, dur_ms))]
    if steps:
        text_spids = {sp.shape_id for sp in slide.shapes if getattr(sp, "has_text_frame", False)}
        parts.append(etree.fromstring(timing_xml(steps, text_spids)))
    for el in parts:
        ext.addprevious(el) if ext is not None else sld.append(el)
```
