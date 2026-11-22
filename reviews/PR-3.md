# PR-3 review: feat(evals): T-005 OpenPhish feed polling, hash-only manifest (v2 of #1)

- Former PR #3 · local branch `keep/feat/evals-collect-v2` · head `0c34653` (one commit on top of `21f3c4c`)
- Task: T-005 (builder-evals, P0) · follow-up to `reviews/PR-1.md` · reviewer: supervisor (L2) · 2026-11-22
- The GitHub repo is being recreated, so this was reviewed from the local branch only. No `gh` posting.

## Verdict: **APPROVE**

Every blocking finding from PR-1 is fixed, and the checks below ran and passed. The branch history doesn't contain `f56e4ec`. The manifest is strictly hash-only and rebuilds byte-for-byte from the private raw rows. A fixed-seed sample matched 60/60.

## Checks run (worktree `scratchpad/fl-review-3`, detached at `0c34653`)

T-001 isn't merged, so `make test`, `make scan`, `make eval-gate` and `tests/contracts` don't exist yet. I ran the PR's own commands instead.

| Command | Result |
|---|---|
| `uv run --no-project --with pytest --with httpx --with tldextract pytest evals/collect/tests -q` | exit 0, `8 passed in 0.19s` |
| `uvx ruff check --isolated evals/collect` (ruff 0.17.3, default rules; there's no repo config yet) | exit 0, `All checks passed!` |
| `uvx ruff format --isolated --check evals/collect` | 3 files would be reformatted (informational only: no repo formatter config yet, and the PR didn't claim format) |
| `gitleaks git . --no-banner` | exit 0, `20 commits scanned … no leaks found` |
| `gitleaks dir . --no-banner` | exit 0, `no leaks found` |
| `git merge-base --is-ancestor f56e4ec keep/feat/evals-collect-v2` | exit 1 (not an ancestor: the defanged-URL commit is not in this history) |
| `git log -p main..keep/feat/evals-collect-v2 \| grep -ciE 'hxxp\|url_defanged\|\[\.\]'` | `0` |
| `git log -p main..… \| grep -E '^\+.*https?://'` (excluding the manifest) | only the OpenPhish feed URL, the terms URL and test hosts (`*.example.test`, `evil.example.com`, `example.co.uk`, `foo.github.io`) |
| `grep -cEi 'hxxp\|https?:\|://\|\[\.\]\|www' evals/manifests/phishing.manifest.jsonl` | `0` |
| `git merge-tree --write-tree main keep/feat/evals-collect-v2` | exit 0 (merges cleanly with `main` `f8e79c4`) |
| `git check-ignore -v data/private/feeds/openphish/20261122.jsonl` | `.gitignore:8:data/private/` |
| `scratchpad/probes/pr3_verify.py` (run with `python -I`, raw rows from `data/private/feeds/openphish/`) | manifest 300 = raw 300; one key set `{url_sha256, registrable_domain_sha256, first_seen, feed}` (`tld` removed); 300 unique URL hashes, 233 unique domain hashes, 0 malformed hex; rebuild from raw == committed manifest: **True**; raw `sha256 == sha256(url)`: True; registrable-domain strings in manifest: 0; hosts: 0; non-hex host labels of 4+ chars: 0 of 279 |
| Fixed-seed sample (seed `20261122`, k = max(20%, 30) = 60) | 60/60 correct (row equals the rebuilt row, domain string absent) |

## PR-1 findings: status
1. Defanged URLs in history: **fixed** on this branch (one clean commit). See the L1 note below about the old local refs.
2. `tld` plaintext field: **fixed** (`manifest_row`, `openphish.py:105-112`; test at `tests/test_openphish.py:39`).
3. ruff: **fixed** (clean with default rules).
4. PR description: **fixed**. It describes the hash-only fields, 8 tests, `FL_DATA_DIR` and `--rebuild-manifest`.
5. Rate guard tested only on the helper: **fixed**. `test_poll_refuses_before_http_and_main_returns_3` monkeypatches `httpx.stream` and `httpx.get` to fail the test, and asserts exit 3.
7. No response size cap: **fixed**. The body is streamed and capped at 5 MB (`openphish.py:193-203`).
9. Corrupt `state.json`: **fixed**. Distinct `CorruptState`, exit 4, tested.
6 and 10 are still open, as expected. Keyed hashing is an L1 call, and pinning waits for T-001.

## Findings (all non-blocking)
1. **LOW** `openphish.py:156-158`: `process_feed` parses `state.json` again without the `CorruptState` guard. `poll()` always calls `check_rate_guard` first, so this can't be reached from the CLI. It is reachable from direct callers, though, so reuse the guarded parse.
2. **LOW**: the unsalted `registrable_domain_sha256` can still be reversed with a domain dictionary (PR-1 finding 6). This is still an L1 decision; nothing is recorded in DECISIONS.md yet.
3. **INFO**: every row still has the same `first_seen` (`2026-11-22T11:56:59Z`), so T-020's temporal cut needs later polls. `scripts/collect_loop.sh` handles that.

## Note for L1 (repo recreate)
The local refs `feat/evals-collect` and `remotes/origin/feat/evals-collect` still contain `f56e4ec` (`git branch -a --contains f56e4ec`). Don't push them, or the bundle refs that contain them, to the new public repo. Push `keep/feat/evals-collect-v2` only.

## Eval impact
This adds 300 OpenPhish rows (233 distinct registrable-domain hashes). The figures come from the committed manifest via the probe above. No `evals/results/` artifact exists yet, and `evals/baseline.json` is unchanged.
