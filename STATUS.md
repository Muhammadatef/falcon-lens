# STATUS — Falcon Lens

**Now:** Phase 0 → 1 (building in parallel) · updated Sun 22 Nov 17:10 GST
**Deadline:** Wed 25 Nov 08:00 · **Freeze:** Tue 24 Nov 22:00

## Gates
| Gate | Target | State |
|---|---|---|
| G0 `make up` healthy | Sun 19:00 | ⏳ in progress |
| G1 `make smoke` URL → verdict | Mon 06:00 | — |
| G2 `make eval` baseline | Mon 14:00 | — |
| G3 redteam 0%, scans clean, 5 dashboards | Mon 22:00 | — |
| G4 MVP (organiser rule) | Tue 08:00 | — |
| G5 Sentinel incident from replay | Tue 15:00 | — |
| G6 `make demo` + `make submission` | Tue 20:00 | — |

## In flight (local branches / PRs)
| Area | Branch | State |
|---|---|---|
| Skeleton + Docker + PR CI | feat/platform-skeleton | fixing supervisor G0 findings (sandbox isolation, deps, ports, CI) |
| SSRF guard | feat/security-ssrf-egress | built (151 tests); in review |
| URL lookalike signals | feat/signals-url | built (55 tests); in review |
| Arbiter + hard rules | feat/core-arbiter | built (917 tests); in review |
| OpenPhish collection (hash-only) | feat/evals-collect-v2 | built; in review |
| Legit URL set + synthetic messages | feat/evals-legit-and-qwen | built (411 URLs); in review + batch audit |
| Sentinel core rules | feat/sentinel-core | round-1 fixes done (86 tests) |
| Sentinel LangGraph agent | feat/sentinel-graph | built (123 tests); PR opening |
| Check API + SSE + smoke | feat/api-check (PR #4) | built (45 tests); smoke vs real worker pending |
| Cascade + worker | feat/core-cascade | building — **G1 critical path** |
| AI investigator + router | feat/core-agent | building |
| Sandbox + fixtures | feat/sandbox-capture | building |
| Domain/cert/feed signals | feat/signals-domain | building |
| Message/email/image signals | feat/signals-message | building |
| Metrics + 6 dashboards + alerts | feat/obs-metrics | building |
| Real web app (Fable 5.2) | feat/web-app | building |
| README + animated diagrams (Fable 5.2) | feat/docs-readme | building |

## Blockers / owner asks
- None blocking. Open design questions (theme / radar vs map / digits) can wait.
- Contributor: @Abdulrahman-alseiari invited — tasks in docs/CONTRIBUTOR_TASKS.md.

## Feeds
Safe Browsing: **disabled** (no key) · URLhaus: **disabled** (no key) · OpenPhish community: pending terms check

## Latest metrics
None yet. Metrics appear here only from `evals/results/` artifacts.

## Works / partial / cut
- Works: —
- Partial: —
- Cut: —
