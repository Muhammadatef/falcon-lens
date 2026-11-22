# PR-8 review: feat(evals): legit URL set + scripts/qwen_task.py + synthetic message spec

- Former PR #8 · local branch `keep/feat/evals-legit-and-qwen` · head `ab4b2d7`
- Tasks: T-020 (legit part) and the local-model runner (builder-evals, P0) · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22
- The GitHub repo is being recreated, so this was reviewed from the local branch only. No `gh` posting.

## Verdict: **CHANGES REQUESTED**

The **legit URL set is good**. All 73 official rows sit on a `verified_domains` entry of their own brand, there are no phishing or lookalike URLs, and the categories meet EVALS (411 rows, 215 hard negatives). The **runner is not ready**. Its validation passed a batch that my audit found 96.9% wrong (`reviews/QWEN-qwen-msg-001.md`, REJECTED), it has no tests for the validation pipeline, and the spec has the wrong Arabic name for the demo brand. Ruff also fails.

## Checks run (worktree `scratchpad/fl-review-8`, detached at `ab4b2d7`)

| Command | Result |
|---|---|
| `uv run --no-project --with httpx --with jsonschema --with pytest pytest scripts/test_qwen_task.py -q` | exit 0, `4 passed in 0.06s` |
| `uvx ruff check --isolated scripts evals` (ruff 0.17.3 defaults) | **exit 1, `Found 14 errors`**: `C408` ×8 (`collect_legit_urls.py:212-237`), `SIM905` (`:104`), `EXE001` (`qwen_task.py:1`, shebang but not executable), `FURB167` (`qwen_task.py:56,155`), `RUF100` (`test_qwen_task.py:11`) |
| `gitleaks git . --no-banner` | exit 0, no leaks |
| `git merge-tree --write-tree main keep/feat/evals-legit-and-qwen` | **exit 1**, conflict in `DECISIONS.md` |
| `scratchpad/probes/pr8_legit.py` (`python -I`, tldextract 5.4.0 private PSL, `data/brands.yaml` from main) | 411 rows, 411 unique URLs, 212 registrable domains; all `https://`; **73 brand rows, 0 not on their brand's verified_domains**; 0 rows on a verified domain without `brand_id`; 0 unknown brand ids; **1 registrable-domain mismatch** (`gov.uk`, finding 6); brands with no row: `emirates_islamic`, `emirates_nbd`, `falcon_demo_bank` |
| Category counts | official_gov 48, official_bank 18, popular 130, hard_negative_{login 56, payment 50, deeplink 68, shortened 36, new_domain 5}. This meets EVALS ≥300 / ≥100 hard negatives. Every shortener is first-party (youtu.be, aka.ms, g.co, apple.co, go.microsoft.com) |
| Live-phishing or lookalike check (manual read of all non-popular rows plus the brand cross-check) | none. Every row is a well-known legitimate site or a verified official domain |
| `scratchpad/probes/pr4_legit.py` (PR-4 `validate_url` over the set) | 0 of 411 blocked |
| `scratchpad/probes/pr5_legit.py` (PR-5 URL signals over the set) | 0 risk evidence |
| Spec sha256 vs batch manifest | both `772a75eb…addd7` |
| Batch audit | see `reviews/QWEN-qwen-msg-001.md`: **31/32 wrong, REJECTED** |

## Findings

### Blocking
1. **HIGH: the runner's validation lets clearly invalid items through.** `run()` (`scripts/qwen_task.py:192-214`) checks the schema, the *declared* constraint fields and a regex blocklist. As a result:
   - 37 of 40 `language: "msa"` items are English;
   - 25 items name UAE Pass or ICP outside `uae_pass_icp_impersonation`;
   - 12 links are malformed (`هxxps://`, `هكسبيس://`);
   - one has a real-format phone (`971 50 123 4567`, which escapes `\+971\s?\d` because it has no `+`);
   - one item is a verbatim copy of a few-shot example.

   *Fix:*
   - (a) per-stratum language/script validation of `text_field`;
   - (b) link and phone **allow-lists** in place of the blocklist (every link-like token must fully match the spec's placeholder; reject 7+ digit runs);
   - (c) subtype-aware entity rules from the spec (UAE Pass/ICP only in their subtype), plus Arabic real-brand names (شرطة أبوظبي, اتصالات, أرامكس …);
   - (d) de-dup against `spec.examples`;
   - (e) record every rejection reason in the manifest `counts`.

   The spec should carry (b) and (c) as data, for example `allowed_link_regex`, `allowed_phone` and `entity_rules: {pattern: allowed_subtypes}`, so the script stays generic.
2. **MEDIUM: no tests for the pipeline.** `scripts/test_qwen_task.py` covers only `normalise`, `jaccard`, `plan_strata` and `parse_items`. Add an offline end-to-end test that drives `run()` with `httpx.MockTransport` (or an injected `call_model`) returning a fixed item list. Assert that each rejection class (schema, constraint, wrong script, bad link, real phone, out-of-subtype entity, example copy, duplicate) is counted and excluded, that accepted items carry `synthetic/task_id/kind`, that the manifest has `audit: PENDING`, and that output goes only to `work/qwen/<task>/`.
3. **LOW: Falcon Demo Bank has the wrong Arabic name in the spec.** Rule 1 of `evals/specs/synthetic_messages_v1.json` says «بنك فالكون التجريبي». `data/brands.yaml` (`name_ar`, `keywords_ar`) and the PR-7/PR-5 Arabic strings use «بنك الصقر التجريبي». Messages that use the spec's name won't match the brand registry tokens. *Fix:* use «بنك الصقر التجريبي» and bump the spec to `_v2`.
4. **LOW (gate): ruff fails** with 14 errors (above). Run `ruff check --fix`, `chmod +x scripts/qwen_task.py` (or drop the shebang), and remove the unused `noqa`.

### Non-blocking
5. **Model choice for re-runs**: `qwen3:4b` can't write usable Gulf Arabic or Arabizi (QWEN audit). The re-run (`qwen-msg-002`) should use a stronger local model through `FL_LOCAL_WORKER_MODEL`. L1 records which one.
6. **LOW** `legit_urls.csv:188`: `https://gov.uk/` has `registrable_domain=gov.uk`, but `gov.uk` is itself a public suffix (tldextract gives an empty eTLD+1). Domain-grouped splits need a real eTLD+1. Use `https://www.gov.uk/` with `registrable_domain=www.gov.uk` (as the PSL treats it), or drop the row.
7. **LOW**: `https://aka.ms/vs/17/release/vc_redist.x64.exe` (shortened) redirects to an `.exe` download. The legit set is replayed through the sandbox, so swap it for a page link.
8. **INFO**: `hard_negative_new_domain` has 5 rows registered in 2024, about two years old on 2026-11-22, so none of them exercises `domain.age < 30` (SCORING §2). It's a "newer company" set, not a "new domain" set. Rename it, or add a note to EVALS. Every legit row has `first_seen = 2026-11-22`, so the temporal cut needs a rule for the legit set (T-020).
9. **INFO**: HIERARCHY says de-dup uses "MinHash". Exact shingle Jaccard is stricter and fine at this n (DECISIONS line). L1 may want to edit HIERARCHY to "shingle Jaccard".
10. Rebase on `main`. `DECISIONS.md` conflicts.

## Eval impact
- The legit set adds 411 rows (73 official, 215 hard negatives). The counts come from my probe over the committed CSV. There is no `evals/results/` artifact yet.
- Batch `qwen-msg-001` is **rejected** and must not enter any dataset. The messages set (EVALS ≥150) is still unmet.
