# PR-7 review: feat(evals): legit URL set + scripts/qwen_task.py + synthetic message spec v2

- GitHub PR #7 · branch `feat/evals-legit-and-qwen` · head `14a0a28` · base `main` (`845c314`)
- Tasks: T-020 (legit part) and the local-model runner (builder-evals, P0) · **round 2 of 2** (round 1 was former PR #8: `reviews/PR-8-former-evals.md`) · reviewer: supervisor (L2) · 2026-11-22
- The earlier `reviews/PR-7.md` (former arbiter PR) is preserved as `reviews/PR-7-former-arbiter.md`.
- L1 decisions applied:
  - legit URLs stored defanged in the CSV is **accepted**;
  - `scripts/tests` collection comes with PR #17, so I'm not blocking on it here (I ran it directly).

## Verdict: **APPROVE**

All four round-1 blockers are fixed and verified, and every check ran and passed. The runner now does what its contract needs:
- validation on the text, not the declared field;
- allow-lists for links and phones;
- subtype-aware entity rules;
- few-shot copy rejection;
- every rejection reason in the manifest;
- an offline end-to-end test.

The runner's output still goes through the supervisor audit, and that audit just rejected `qwen-msg-002` (43.8%, `reviews/QWEN-qwen-msg-002.md`). The gate works: nothing from `work/qwen/` can enter `evals/` without an APPROVED audit.

One new defect (finding 1) is **approved with a required follow-up** (TASKS T-029, P1). It must land before the next synthetic run (`qwen-msg-003`). L1 may make it blocking instead; it's a one-line fix plus a test.

## Checks run (worktree `/tmp/fl-review-7`, detached at `14a0a28`)

| Command | Result |
|---|---|
| `make test` (ruff check, ruff format --check, mypy, pytest) | exit 0: `All checks passed!`, `74 files already formatted`, mypy `Success: no issues found in 27 source files`, `310 passed, 1 skipped` |
| `uv run pytest scripts/tests -q` (not yet collected by `make test`; PR #17) | exit 0, `9 passed in 0.08s` (4 helper tests + 5 pipeline tests, including the fake-model end-to-end run) |
| `uv run pytest tests/contracts -q` | exit 4, `file or directory not found: tests/contracts`. There are no contract tests on `main` yet. This PR touches no `contracts/` file, so N/A |
| `make eval-gate` | exit 0, `SKIPPED - evals/baseline.json does not exist yet … This is NOT a pass` (no harness yet; nothing gated) |
| `make guard` | exit 0, `check_no_live_urls: ok` |
| `make scan` | exit 0: gitleaks `no leaks found`; pip-audit `No known vulnerabilities found`; pnpm audit clean; trivy 0 vuln/secret/misconfig HIGH+; syft not installed (SBOM skipped, warning only) |
| `git merge-tree --write-tree origin/main HEAD` | exit 1, conflict in `DECISIONS.md` *without* attributes; **0 conflicts** with main's `.gitattributes` (`DECISIONS.md merge=union`). L1 should merge locally (union driver) or rebase; GitHub's web merge ignores the union driver |
| `sha256sum evals/specs/synthetic_messages_v2.json` | `9cf6c5c8…274204`, the same as the `qwen-msg-002` manifest `spec_sha256` |
| Legit-set probe `scratchpad/probes/pr8_legit.py` (tldextract private PSL, `data/brands.yaml` at head) on the CSV refanged with `url.replace("hxxp","http",1)` | 410 rows, 410 unique URLs, 212 registrable domains, **0 issues** (registrable-domain mismatch 0, official rows not on their brand's `verified_domains` 0, unknown brand 0, verified domain without brand 0). Every URL starts with `hxxps://`; 0 `https?://` strings in the CSV |
| Category counts (same probe) | popular 130, official_gov 48, official_bank 18, hard_negative_{deeplink 68, login 56, payment 50, shortened 35, new_domain 5} = 214 hard negatives (EVALS ≥ 300 rows / ≥ 100 hard negatives: met) |
| Rotation probe `scratchpad/rot/rot_probe.py` (fake `model_fn` records the requested variant per stratum; v2 spec, 54 calls) | **each scam stratum was asked for exactly one subtype**: gulf→urgency 7/7, msa→fake_fine 7/7, english→delivery_fee 7/7, arabizi→bank_otp 7/7 (finding 1) |
| `QWEN-qwen-msg-002` audit | 14/32 wrong = 43.8%, **REJECTED** (separate report) |

## Round-1 findings: status

| # | Round-1 finding | Status | Evidence |
|---|---|---|---|
| 1a | Language checked on text | **fixed** | `qwen_task.py:112-135` `check_language` (script ratio + `require_any`/`forbid_any`/`require_digit_letter`), applied at `:177-183` to the text after placeholders are stripped; test `test_language_checked_on_text_not_declared_field` |
| 1b | Link and phone allow-lists | **fixed** | `:138-150`; the allowed link is anchored with `(?<!\w)` (so «هxxps» fails) and `(?![\w\[\]?=&#%]\|\.\w)` (so `?code=` fails); phones reject `+d`, `00d`, `0dd` and 7+ digit runs after Arabic-Indic digit folding; tests cover every round-1 malformed form (`هxxps`, `Hxxps`, `example.test`, `https`, query, empty path, `www.`, other host; `971 50 123 4567`, `٠٥٠…`) |
| 1c | Subtype-aware entities and Arabic brand names | **fixed** | spec `entity_rules` (UAE Pass/ICP only in `uae_pass_icp_impersonation`; شرطة، اتصالات، أرامكس، ديوا، سالك … never); `:153-157`. Batch 002 had 0 out-of-subtype UAE Pass/ICP |
| 1d | De-dup against `spec.examples` | **fixed** | `:282`, `:328` (Jaccard ≥ 0.7 → `rejected_example_copy`); batch 002 max 0.60 |
| 1e | Every rejection reason in the manifest | **fixed** | `:346-366`; batch 002 manifest lists 6 reasons |
| 2 | End-to-end test with a fake model | **fixed** | `scripts/tests/test_qwen_task_pipeline.py:75-136`: injected `model_fn`, 11 items, asserts each of the 9 rejection classes is counted once, accepted rows carry `synthetic/task_id/kind`, `audit: PENDING`, and output only goes to `work/qwen/<task>/` |
| 3 | Arabic demo-brand name | **fixed** | spec v2 rule 1 «بنك الصقر التجريبي»; batch 002 has 0 «فالكون» |
| 4 | Ruff | **fixed** | `make test` lint passes; `scripts/qwen_task.py` is mode 100755 |
| 6 | `gov.uk` public suffix | **fixed** | only `hxxps://www.gov.uk/` remains; probe 0 mismatches |
| 7 | `.exe` shortener | **fixed** | removed (shortened 36 → 35) |
| 8 | Thin `new_domain` | acknowledged | DECISIONS line (RDAP gaps, 5 rows). T-020 still has to define the temporal-cut rule for the legit set (all `first_seen` = 2026-11-22) |
| 9 | MinHash vs shingle Jaccard | acknowledged | DECISIONS line. HIERARCHY wording is still L1's call |
| 10 | Rebase | resolves under union merge | see merge-tree row |

## Findings (new in round 2)

### Approved with required follow-up
1. **MEDIUM (eval validity): the variant rotation is locked to the stratum.** `scripts/qwen_task.py:304` has `variant = variants[call_idx % len(variants)]` with `call_idx` global across strata. With 8 active strata and 8 scam variants, stratum *i* always gets variant *i*, so `prize`, `investment`, `job` and `uae_pass_icp_impersonation` are never requested until other strata fill up. The rotation probe reproduces it (table above), and it explains the `qwen-msg-002` skew (scam/msa = fake_fine 21/24; scam/gulf = urgency 18/24). Per-language metrics on such a batch would be confounded with subtype.
   - *Fix:* a per-stratum counter (`s["calls"] = s.get("calls", 0) + 1; variant = variants[s["calls"] % len(variants)]`).
   - *Test:* drive `run()` with a recording `model_fn` and assert that every variant of every stratum is requested at least once within `len(variants)` calls of that stratum.
   - Tracked as **T-029**; it must land before `qwen-msg-003`.

### Non-blocking
2. **LOW (path safety)**: `--task` goes straight into `ROOT / "work" / "qwen" / args.task` (`:285`), so `--task ../../evals/x` would write outside `work/qwen/`. It's a local CLI, but HIERARCHY says output goes "only" to `work/qwen/<task-id>/`. Validate with `re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.task)`. Fold this into T-029.
3. **INFO (genericity)**: `:181` hard-codes `\+971 5X XXX XXXX|X{2,}|Falcon Demo Bank|AED` as text stripped before the language check. It belongs in the spec (for example `language_strip_regex`). Fold this into T-029.
4. **INFO (validator gaming)**: the dialect markers in `language_rules` are a necessary check, not a sufficient one. Batch 002 shows marker stuffing (27/40 Gulf items contain «هالحين») and nonsense Arabizi digit-tokens. That's not a code defect: the audit is the real gate. Don't add more markers to "fix" quality.
5. **INFO (hand-typed number)**: the PR title says "411 verified rows". The CSV has **410** data rows (411 lines with the header; DECISIONS correctly says 410). Edit the title on merge. Future docs should quote counts from an `evals/results/` artifact (T-020 manifest).
6. **INFO**: `collect_legit_urls.py` makes direct `httpx` GETs to its hard-coded official and popular list. That's acceptable for an offline research collector (it isn't a service path and takes no user input). It must never be imported by services; `safe_fetch` applies to anything user-driven.

### Security and policy checklist
- Defensive-only: no live phishing URLs (guard ok; the CSV is legitimate sites only, defanged), no logos, no form submission.
- Secrets: gitleaks and trivy clean. The manifest records `ollama_base_url` (local URL, no credentials).
- No "safe" verdict wording. The only hit is the prompt line telling the model *never* to say "safe" (`qwen_task.py:56`).
- Contracts untouched. No XSS/CSP surface (no web changes).

## Eval impact
- The legit set adds 410 rows (73 official, 214 hard negatives). The counts come from my probe over the committed CSV, not from an `evals/results/` artifact; T-020 must emit the manifest artifact.
- Synthetic messages: `qwen-msg-002` is **REJECTED** (43.8%). EVALS' ≥ 150 messages target is still unmet. The next batch needs T-029 plus a stronger model or owner-written Gulf/Arabizi strata (see the QWEN report).
- No metrics were produced, and none are claimed.
