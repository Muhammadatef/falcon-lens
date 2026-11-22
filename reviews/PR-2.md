# PR-2 review: feat(sentinel): deterministic core (correlation, R1-R5, incidents, replay fixture)

- PR: https://github.com/Muhammadatef/falcon-lens/pull/2 · branch `feat/sentinel-core` · head `3c5fbd2`
- Builder: builder-sentinel · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22
- References: ADR-002, `contracts/event.schema.json`, `contracts/incident.schema.json`, docs/CONTRACTS.md invariants 5 and 6
- L1 decisions applied: R2 = 7 days and R4 = 30 days are **accepted**. The contract notes (`previous_verdict`, `script_fingerprint`) are already on `main` in `21f3c4c`, so I did not block on them.

## Verdict: **CHANGES REQUESTED**

The core is in good shape. Batch replay is deterministic, replaying the same events twice gives the same result, incidents validate against the contract, no raw text reaches an incident, every fixture uses an invented `.test` domain, and there are no URLs. Five problems block the merge: two gate failures (ruff, and a mypy command that can't be reproduced), incident ids that change with event arrival order, an R4 detection gap, and one domain that isn't `.test`. The branch also conflicts with `main` in `DECISIONS.md`.

## Checks run

These ran in the worktree `/tmp/fl-review-2`, detached at `3c5fbd2`. T-001 isn't merged, so `make test`, `make scan`, `make eval-gate` and `tests/contracts` don't exist yet. I ran the PR's own commands instead.

| Command | Result |
|---|---|
| `PYTHONPATH=services/sentinel uv run --no-project --with pytest --with pyyaml --with jsonschema --with python-ulid pytest services/sentinel/tests -q` | exit 0, `28 passed in 0.29s` |
| `uvx ruff check services/sentinel` (ruff 0.17.3, no repo config; `--isolated` gives the same result) | **exit 1**, `Found 5 errors`: `sentinel_core/events.py:33:33 FURB162`, `sentinel_core/incidents.py:193:16 FURB192`, `sentinel_core/rules.py:91:9 SIM103`, `sentinel_core/rules.py:123:30 RUF007`, `tests/test_replay.py:1:1 I001` |
| `cd services/sentinel && uv run --no-project --with mypy --with types-PyYAML --with jsonschema --with python-ulid mypy --strict sentinel_core` | **exit 1**, `incidents.py:13` and `events.py:11`: `Library stubs not installed for "jsonschema" [import-untyped]`, `Found 2 errors in 2 files` |
| same command plus `--with types-jsonschema` | exit 0, `Success: no issues found in 8 source files` |
| `gitleaks git . --no-banner` | exit 0, `12 commits scanned … no leaks found` |
| `gitleaks dir . --no-banner` | exit 0, `no leaks found` |
| `git diff origin/main...HEAD` grep `^\+.*(https?://\|hxxp\|www\.)` | one hit, `correlate.py:26`, which is the `removeprefix("hxxps://")` literal in `refang`. No URLs in data or tests |
| `git log -p origin/main..HEAD` grep `^\+.*https?://` | `0` |
| Domain-like tokens added under `services/` that aren't `.test` | only `x.gov.ae` (`tests/test_rules.py:126`), see finding 5 |
| `safe` wording grep on the diff | no matches |
| network, subprocess, `eval`/`exec`, pickle or `yaml.load` in the diff | none (`yaml.safe_load` only, `rules.py:49`) |
| Image or binary files in the diff | none |
| `git merge-tree --write-tree origin/main HEAD` | **exit 1**, `CONFLICT (content): Merge conflict in DECISIONS.md` (with L1's `21f3c4c`) |
| Probe `scratchpad/pr2/probe.py` (run with `python -I`, on the fixture from `generate()`) | P1 batch: 3 incidents (campaign R1+R2, kit_reuse R2, reputation_flip R4). P2 one event per `process()` call, in order: identical to batch. **P3 one event per call, shuffled: ids differ for seeds 1 and 2.** **P4 restart (new `Sentinel`, same store, only the remaining events): R4 incident lost.** P5 restart plus full replay: identical. **P6 R4 nws→suspicious→dangerous: 0 matches.** **P7 `previous_verdict` on a domain's non-first event: 0 matches.** P8 `registrable_domain("http://falcon-demo-bank-x.test/a")` → `"http:"`. P9 R2 fires on 3 events with no `registrable_domain` |
| Probe `scratchpad/pr2/probe2.py` (50 seeded shuffles, one event per call) | **44/50 seeds give different `incident_id` and `created_at` for the campaign** (for example `10:40:00Z` instead of `10:21:00Z`). Types, rule_ids and linked event sets match batch in 50/50 |

## Findings

### Blocking

1. **LOW (gate): ruff fails** with 5 errors (listed above). The PR says "ruff clean", but that only holds with an older ruff. *Fix:* use `min(...)` at `incidents.py:193` and `itertools.pairwise(fs)` at `rules.py:123`, return the condition directly at `rules.py:91-93`, and run `ruff check --fix` for `test_replay.py:1`. At `events.py:33`, Python 3.12 `fromisoformat` accepts `Z`, so remove the `.replace`, or add a `# noqa: FURB162` with a reason. Either way, keep a test for `Z` input.
2. **LOW (gate): the mypy command can't be reproduced as documented.** `mypy --strict` needs `types-jsonschema`, and neither the PR body nor `DECISIONS.md` mentions it. *Fix:* add `types-jsonschema` to the deps line in DECISIONS (so T-001 pins it) and to the PR's check command.
3. **MEDIUM: incident ids and `created_at` depend on arrival order.** `incidents.py:129` builds the id from `triggered_at` and `first.event_id` *at the moment the rule first fires*, and `incidents.py:122` freezes `created_at` the same way. With at-least-once delivery from Redis Streams, retries and `XAUTOCLAIM` redeliver events out of order. When events arrive one per `process()` call in shuffled order, the campaign id changes in 44 of 50 seeds. `test_replay_order_independent` (`tests/test_replay.py:52-56`) doesn't catch this: it passes the reversed list in **one** `process()` call, and `process()` sorts the batch first (`incidents.py:174`), so the test never exercises arrival order. Counts, types, rule_ids and event sets were stable in all 50 seeds, so the ADR-002 guardrail ("incident counts are reproducible") holds.
   *Fix (choose one, and state it in DECISIONS):*
   (a) Make the id canonical over the converged incident, for example derived from rule id, group key and the earliest event in the session. Accept that an id can be re-keyed while the incident is still `open` and nothing external references it yet.
   (b) Narrow the guarantee to "ids are reproducible for a stream replayed in `occurred_at` order (`replay()`); live arrival order may change id and `created_at` but never the count, type, rule_ids or linked events". Rename the test, and add a test that feeds the fixture one event at a time in several seeded shuffles and asserts count, type, rule_ids and event sets against `fx.labels`.
4. **MEDIUM: R4 misses flips with a step in between and ignores `previous_verdict` after the first event.** `rules.py:123` only compares *consecutive* verdicts, so `no_warning_signs → suspicious → dangerous` within 30 days doesn't fire (probe P6). ADR-002 defines R4 as "previously no_warning_signs, now dangerous", which this sequence is. `rules.py:131` reads `previous_verdict` only on the domain's first event (probe P7). *Fix:* for each `to_verdicts` event, fire if any `from_verdicts` event for the same domain falls within `window` before it, or if the event's own `previous_verdict` is in `from_verdicts`. De-dup so one dangerous event creates one match. Add tests for both cases.
5. **LOW: one test domain isn't `.test`.** `tests/test_rules.py:126` uses `registrable_domain("x.gov.ae")`. It's only parsed, but the review rule allows invented `.test` domains only, and `.ae` is a live ccTLD. *Fix:* use a never-delegated code such as `x.gov.zz` (ISO user-assigned), or another `.test` form that exercises the three-label branch.
6. **Rebase needed.** `DECISIONS.md` conflicts with `21f3c4c`. While rebasing, drop the line "Proposed contract note for L1: document `previous_verdict` and `script_fingerprint`" (DECISIONS diff line 6), because L1 has already done it. L1's line also covers the R2/R4 window acceptance, so mark the builder's "assumed" windows line as accepted or fold it into L1's line.

### Non-blocking (fix now or carry to the P5 Sentinel consumer card)

7. **Restart loses history.** `Sentinel._feats` (`incidents.py:163`) is in memory only. After a restart that doesn't replay history, R4 never fires for a flip that spans the restart (probe P4), and the same applies to R2's 7-day and R4's 30-day windows. ADR-002 says the agent must survive restarts. The Redis consumer PR must rehydrate features from the stream or a feature store at startup. This is an acceptance test for that card.
8. **`refang` doesn't strip `http(s)://`** (`correlate.py:26`), so `registrable_domain("http://…")` returns `"http:"` (probe P8). The contract says `domain_defanged`, but `registrable_domain` in verdict payloads is free-form. *Fix:* strip any `scheme://`, keep only `[a-z0-9.-]` hostnames, and treat anything else as no domain.
9. **The distinct-unit fallback inflates counts.** `rules.py:109` counts an event with no `domain` as a distinct unit (its event_id), so R2 fires on three domain-less events (probe P9). *Fix:* skip events that lack the `distinct` feature.
10. **R1 doesn't check "new".** ADR-002 says "≥3 *new* lookalike domains". The rule counts any lookalike, whatever its `registered_at` or `first_seen`. Either add a freshness condition (for example `registered_at` or `first_seen` within N days) or have L1 record that "new" means "first observed in the window".
11. **The raw-text guard is a denylist of key names** (`events.py:18`). A payload with `snippet`, `subject` or `title` passes. Prefer a per-type allowlist of payload keys that matches the contract's payload description.
12. **ISO strings are compared as strings** (`incidents.py:112`, `incidents.py:123`). With fractional seconds, `"…:00.5Z" < "…:00Z"`, so the ordering is wrong. Compare `datetime` values instead.
13. **Single-linkage clustering** (`correlate.py:100`) can chain simhashes more than 6 bits apart (A~B~C). Either document it as intended or use leader or centroid bucketing.
14. **Performance.** Every `process()` call re-clusters the whole history, pairwise. That's fine for the replay fixture of about 100 events, but the live consumer needs incremental buckets.
15. `REPO_ROOT = parents[3]` (`events.py:13`) ties schema loading to the repo layout. Make the contracts path configurable before the T-001 container build.
16. The `format: date-time` keyword isn't enforced, and `parse_time` accepts the date-only `2026-11-20`. Use `FormatChecker` or check explicitly.

### Supervisor follow-ups (no builder action)
- `TASKS.md` has no card for this work. Sentinel is backlog P5, and this PR is early core work. Once L1 confirms the id guarantee in finding 3, I'll add a card (Sentinel core, builder-sentinel, `feat/sentinel-core`) with the acceptance tests from findings 3, 4 and 7.

## What passed (verified)
- R1–R5 each have fire, no-fire and replay-idempotence tests (`tests/test_rules.py`, 20 tests, `20 passed in 0.11s`). Every rule except R4 matches ADR-002's thresholds and windows (R4: finding 4).
- The planted stream replayed twice gives exactly one campaign with `rule_ids == ["R1","R2"]`, and three incidents in total, matching `fx.labels`.
- Every incident validates against `contracts/incident.schema.json`. `find_raw_text` finds nothing in any incident, domain indicators are defanged, and no incident contains `http`.
- Fixtures: brand `falcon_demo_bank` only, `.test` domains only, `source: replay` on every event, `labels.synthetic = True`. ASNs are in the documentation and private ranges. Registrar and CA names are "Example …".
- No LLM, network or Redis code. Rules load with `yaml.safe_load` and validate type, severity and detector.

## Eval impact
None on the investigator merge gate, which isn't built yet. The labelled replay stream (`fixtures.generate()`) will seed the Sentinel evals in P5. Any Sentinel incident metric must come from an `evals/results/` artifact produced by that harness, never from this PR's test counts.
