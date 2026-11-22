# PR-7 review: feat(scoring): arbiter + hard rules H1-H6 + template reasons (T-011)

- Former PR #7 · local branch `keep/feat/core-arbiter` · head `ed94670`
- Task: T-011 (agent-core, P0) · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22
- L1 decisions applied (SCORING §6, DECISIONS "SCORING updates from PR #5 and #7"): ε 0.05/0.98, θ 0.70, H3 cap 0.05, intercept −2.2, confidence scaling, `link_verdict` weight 0, and precedence degraded > H3 > H1/H4/H6 are **accepted**. I didn't block on any of them, and the code matches all of them.
- The GitHub repo is being recreated, so this was reviewed from the local branch only. No `gh` posting.

## Verdict: **CHANGES REQUESTED**

The arbiter is correct on every invariant I could attack. One item blocks the merge: `params.yaml` is missing the `url.data_uri` weight that L1 has since put into SCORING §2. The branch also needs a rebase. Everything else is good.

## Checks run (worktree `scratchpad/fl-review-7`, detached at `ed94670`)

| Command | Result |
|---|---|
| `PYTHONPATH=packages/falcon_core/src uv run --no-project --with pytest --with pyyaml --with jsonschema pytest packages/falcon_core/tests/scoring -q` | exit 0, `917 passed in 0.45s` |
| `uvx ruff check --isolated --config 'lint.isort.known-first-party=["falcon_core"]' packages/falcon_core` | exit 1, 1× `I001` at `tests/scoring/test_reasons.py:3`. This is the 88-column default wrapping one import line; with line-length 120 (the builder's config) it's clean. It depends on config, so it's non-blocking. T-001 sets the line length |
| `cd packages/falcon_core && MYPYPATH=src uv run --no-project --with mypy --with types-PyYAML --with pyyaml mypy --strict --explicit-package-bases src/falcon_core/scoring src/falcon_core/i18n` | exit 0, `Success: no issues found in 7 source files` |
| `gitleaks git . --no-banner` | exit 0, no leaks |
| `git merge-tree --write-tree main keep/feat/core-arbiter` | **exit 1**, conflict in `DECISIONS.md` |
| `grep -rniE '\bsafe\b\|آمن' packages/falcon_core/src/falcon_core/{i18n,scoring}` | no matches |
| Invariant fuzz `scratchpad/probes/pr7_fuzz.py` (20 000 seeded cases, seed 7; random signals, families (5% mislabelled), sources (computed/registry/llm/user/openphish), tiers, observed shapes including NaN and inf, confidence in {NaN, 2, −1, 0, 0.5, 0.7, 1}, errors, p_clf in {None, 0, 1, 0.01, 0.5, 0.99}, input types) | **0 violations** of: verdict ∈ enum; p ∈ [0,1] and not NaN; degraded ⇒ not `no_warning_signs`; H3 ⇒ never `dangerous`; H3 and not degraded ⇒ `no_warning_signs`; removing untrusted (llm/user/injection) evidence never raises p or the verdict; reasons cite existing ids, ≤ 3; no "safe"/"آمن" in output; no exceptions |
| `scratchpad/probes/pr7_nws.py` | official fixture domain + H3 → `no_warning_signs`, score 5, `actions.caution` present (3 bilingual lines), reason cites the H3 evidence id; official + RDAP timeout → `suspicious` with `signal_error:domain.age` (degraded beats H3, as L1 decided) |

## Findings

### Blocking
1. **LOW (SCORING conformance): `url.data_uri` weight is missing.** `scoring/params.yaml` `weights:` has no `url.data_uri`. SCORING §2 on `main` (`f8e79c4`) lists `url.data_uri | url | +2.0`, so `_base_weight` (`arbiter.py:127`) returns 0 for it. *Fix:* add `url.data_uri: 2.0` (url family, so it feeds the draft classifier sum) and a test. Also add a test that parses the SCORING.md §2 table and asserts every listed signal has a params entry, so the next SCORING edit can't drift silently.
2. **Rebase needed.** `DECISIONS.md` conflicts with `main`. While rebasing, mark the five "proposal" lines as accepted (L1 recorded them) instead of leaving them as open questions.

### Non-blocking
3. **INFO (contract)**: `actions.report.channels[].value` carries `aman.adpolice.gov.ae` and `cas.adpolice.gov.ae` undefanged. CONTRACTS invariant 5 says "URLs in any output are defanged". These are verified official reporting channels from `config/reporting_channels.yaml`, not attacker URLs, so defanging them would hurt users. L1 should clarify that invariant 5 applies to input-derived URLs only.
4. **LOW**: when `ctx.registrable_domain`/`verified_domains` are absent, H3 trusts `registry.verified_official` evidence on its own (`hard_rules.py:108`). That's fine while only the registry signal emits it. T-012 should always pass both so the cross-check is active.
5. **LOW**: signal names `domain.age` / `domain.cert_age` with `observed.age_days` differ from SCORING's `domain.age_days` wording. Make T-008 use these names exactly (the PR body says so). No change needed here.
6. The PR's open risks (params.yaml ownership moving to builder-evals after the fit, package data for `*.yaml`, T-022 reputation features, cascade `extra_degraded_reasons`) are accepted as carried items.

## Eval impact
Draft parameters only (`params.yaml` `draft: true`, marked not fitted). No metrics were produced, and none are claimed.
