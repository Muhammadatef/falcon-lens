# PR-1 review: feat(evals): T-005 OpenPhish feed collection (polling part)

- PR: https://github.com/Muhammadatef/falcon-lens/pull/1 · branch `feat/evals-collect` · head `d2d84b3`
- Task: T-005 (builder-evals, P0) · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22

## Verdict: **CHANGES REQUESTED** (and escalated to L1 for finding 1)

Most of the code is good. The poller, rate guard, dedup, the hash-only manifest at HEAD and the private data handling all checked out (see the checks below). Four problems block the merge. One of them (1) is a disclosure that is already public, so merging cannot fix it and the fix needs L1 or the owner.

## Checks run (in the worktree `/tmp/fl-review-1`, detached at `d2d84b3`)

T-001 is not merged yet, so `make test`, `make scan`, `make eval-gate` and `tests/contracts` don't exist. I ran these substitutes instead:

| Command | Result |
|---|---|
| `uv run --no-project --with pytest --with httpx --with tldextract pytest evals/collect/tests -q` | exit 0, `6 passed in 0.13s` |
| `uvx ruff check evals/collect` (ruff 0.17.3, default rules, no repo config) | **exit 1**, `Found 3 errors`: `snapshot_queue.py:14:33 RUF100`, `tests/test_openphish.py:2:8 F401 're' imported but unused`, `tests/test_openphish.py:10:25 RUF100` |
| `gitleaks git . --no-banner` | exit 0, `8 commits scanned … no leaks found` |
| `gitleaks dir . --no-banner` | exit 0, `no leaks found` |
| `git ls-files data/private \| wc -l` | `0` (only `data/brands.yaml` is tracked under `data/`) |
| `git check-ignore -v data/private/feeds/openphish/20261122.jsonl` | `.gitignore:8:data/private/` |
| Manifest structure (python, all 300 rows) | one key set, `{url_sha256, registrable_domain_sha256, tld, first_seen, feed}`; 300 unique `url_sha256`; 233 unique domain hashes; 0 malformed hex |
| `grep -cEi 'hxxp\|https?:\|://\|\[\.\]\|www' evals/manifests/phishing.manifest.jsonl` | `0` |
| `grep -nEi '[a-z0-9-]+\.[a-z]{2,}' evals/manifests/phishing.manifest.jsonl` | no matches |
| Cross-check against the private raw rows (`scratchpad/verify_manifest.py`, run with `-I`, raw from `data/private/feeds/openphish/`) | raw 300 = manifest 300; `--rebuild-manifest` output byte-identical to the committed manifest: True; every raw `sha256` == sha256(canonical url): True; every raw row has `first_seen`: True |
| Leak search over **all** 300 rows | registrable-domain strings in manifest: **0**; full hosts: **0**; non-hex host labels of 4+ chars: **0 of 277** |
| Fixed-seed sample (seed `20261122`, k = max(20%, 30) = 60) | 60/60 correct (url hash, domain hash and first_seen match raw; domain string absent) |
| `git diff origin/main...HEAD` grep for `^\+.*(https?://\|hxxp\|www\.)` | only the OpenPhish feed URL, the terms URL and test fixture hosts (`*.example.test`, `example.co.uk`, `foo.github.io`). No phishing URLs at HEAD |
| `git log -p origin/main..HEAD` grep for URLs | **commit `f56e4ec` adds 300 defanged phishing URLs** (see finding 1) |
| `git show f56e4ec:evals/manifests/phishing.manifest.jsonl \| grep -cE 'hxxps?://'` | `300`; keys `domain_sha256, first_seen, source, url_defanged, url_sha256` |
| `git branch -r --contains f56e4ec` / `gh api repos/{owner}/{repo}` | `origin/feat/evals-collect` / `public`. The commit can be fetched from GitHub by SHA |
| `safe` wording grep on the diff (excluding the manifest) | no matches |
| Image files in the diff | none |

## Findings

### Blocking

1. **HIGH: 300 defanged OpenPhish URLs are in public git history.** Commit `f56e4ec` ("…defanged manifest…") adds `evals/manifests/phishing.manifest.jsonl` with a `url_defanged` field on all 300 rows, and that commit is on the public remote. This breaks DECISIONS.md:52, "(a) The public manifest is **hash-only**: no URLs, defanged or not", and the OpenPhish no-redistribution term (DECISIONS.md:51). HEAD (`d2d84b3`) fixes the file, but a squash merge only cleans `main`. The branch, `refs/pull/1/head` and the commit-by-SHA URL keep serving the old version.
   *Fix (needs L1/owner sign-off because it rewrites public history):* close PR #1, delete the remote branch `feat/evals-collect`, and open a new PR from a fresh branch whose history never contains `f56e4ec` (for example, one commit made from the HEAD tree). Then ask GitHub Support to purge the cached commit and PR ref. Escalated to L1 now, without waiting for round 2.
2. **MEDIUM: the `tld` field is a plaintext host fragment in the public manifest.** `evals/collect/openphish.py:100` writes `"tld": host.rsplit(".", 1)[-1]`. DECISIONS (a) says hash-only, and the card's no-host-fragment requirement covers this field. It also shrinks the dictionary search for reversing `registrable_domain_sha256` (see finding 6). TLD features can be computed from `data/private` when they're needed.
   *Fix:* drop `tld` from `manifest_row` and from the key-set assertion at `tests/test_openphish.py:40-41`, then regenerate with `--rebuild-manifest`. The other option is for L1 to approve it explicitly in DECISIONS.md.
3. **LOW (gate): ruff fails** (exit 1, 3 errors; output above). Remove `import re` at `tests/test_openphish.py:2` and the unneeded `# noqa: E402` at `snapshot_queue.py:14` and `tests/test_openphish.py:10`. While you're there, remove the stray double blank line inside `test_dedup_and_manifest` (`tests/test_openphish.py:44-45`).
4. **LOW: the PR description is wrong about HEAD.** It still says the public manifest has "hxxp(s) URL with `[.]` host dots", says "4 pass" (there are now 6 tests), and asks L1 to choose between defanged and hash-only, which L1 already decided (DECISIONS.md:51-54). It doesn't mention `FL_DATA_DIR`, the main-checkout data-dir resolution or `--rebuild-manifest`.
   *Fix:* rewrite the body to describe the hash-only manifest and its exact fields, list the 6 tests, document `FL_DATA_DIR` and `--rebuild-manifest`, and remove the defanged wording. This applies to the replacement PR from finding 1.

### Non-blocking (fix now or file a follow-up)

5. **Rate-guard test only covers the helper.** `test_rate_guard_refuses_early_and_allows_after` calls `check_rate_guard` directly. Add a test that `poll()` raises `PollTooEarly` before any HTTP call (monkeypatch `httpx.get` to fail the test) and that `main()` returns 3. Point `FEED_DIR` at `tmp_path` so the test never touches the real state file.
6. **Unsalted hashes can be reversed with a dictionary.** `registrable_domain_sha256` is `sha256(eTLD+1)` (openphish.py:99). Anyone with a domain list (zone files, CT logs, the feed itself) can recover the domains. Consider HMAC-SHA256 with a key kept in `.env` or `data/private`. Grouping for splits still works with a keyed hash. Deciding this belongs to L1, not the builder.
7. **No response size cap.** `httpx.get(FEED_URL, …)` (openphish.py:181) reads the whole body. THREAT_MODEL §D asks for size limits; stream the body and cap it (for example at 10 MB). The URL is a constant, so SSRF doesn't apply here. httpx doesn't follow redirects by default, and `raise_for_status` rejects a 3xx.
8. **Fixture hosts.** `example.co.uk` and `foo.github.io` (`tests/test_openphish.py:51-52`) are not reserved names. They are only parsed by tldextract with no network and they aren't phishing hosts, so this is acceptable. Note it for consistency.
9. A corrupt `state.json` ends up in the generic handler and prints "fetch failed" (openphish.py:195-197). Nothing is fetched, so this is safe, but the message is misleading. Catch `JSONDecodeError`/`KeyError` separately.
10. `httpx` is unpinned (tldextract resolved to 5.4.0, which matches DECISIONS.md:38). Pin both when T-001 lands.

### Supervisor follow-ups (no builder action)
- The T-005 acceptance line in `TASKS.md:88` ("manifest rows match `^hxxps?://`") and its scope line ("defanged URL") contradict DECISIONS (a). I will update the card to "hash-only; no URL, host, label or domain strings in git" once L1 confirms finding 2.
- T-005 stays open after this PR: the `make collect` target (needs T-001) and snapshot capture (`snapshot_queue.py` is a stub; needs T-004).

## Eval impact
- Adds 300 OpenPhish phishing rows (233 distinct registrable-domain hashes). The figures come from the committed manifest via the python check above; there is no `evals/results/` artifact yet.
- Every row has the same `first_seen` (`2026-11-22T11:56:59Z`, one poll). So T-020's temporal cut is impossible until more polls arrive at the 12 h interval. The ≥300 target is met by count, but the temporal split depends on feed churn across later polls.
- There is no eval gate yet, so no change to `evals/baseline.json`.

## Posting note
`gh pr review 1 --request-changes -F reviews/PR-1.md` failed: `GraphQL: Review Can not request changes on your own pull request` (the builder and the supervisor share one GitHub account). The review was posted with `gh pr review 1 --comment` instead. The verdict that binds is this file: **CHANGES REQUESTED**.
