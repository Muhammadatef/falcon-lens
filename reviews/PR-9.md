# PR-9 review: fix(signals): PR-5 review changes (fixtures, escapes, url.data_uri, ruff)

- GitHub PR #9 · branch `fix/signals-url-review` · head `405c2d9` · base `main` @ `05c2621`
- Task: T-007 (builder-signals, P0). This is the follow-up to `reviews/PR-5.md`, so it counts as **round 2 of 2** for the T-007 URL signals.
- Reviewer: supervisor (L2) · 2026-11-22

## Verdict: **CHANGES REQUESTED** (one small blocking item, round 2: escalated to L1)

All three blocking findings from PR-5 are fixed, and so are non-blocking findings 5 and 7. Non-blocking finding 4 is now documented. The fix for finding 3 brings a new problem with it. The new `url.data_uri` signal copies the attacker-controlled "mime" text from a `data:` URI straight into `observed`. That text can be a full, non-defanged URL or HTML markup, which breaks CONTRACTS invariant 5 ("URLs in any output are defanged"). It's a two-line fix. Under the two-round rule I'm escalating to L1. L1 can merge after that fix lands, without another full review cycle.

## PR-5 blocking findings: status

| PR-5 finding | Status | Evidence |
|---|---|---|
| 1. Real-brand lookalikes on live TLDs in fixtures | **Resolved** | `adpolicr.com`, `adpolice.com`, `dubaipolice-gov.ae` and `adpolice.gov.ae.verify-fine.xyz` are gone. The typosquat, `tld_swap` and brand-in-subdomain tests now use `falcon-demo-bamk.test`, `falcon-demo-bank.example`, `falcondemobank.test` and `falcon-demo-bank.test.verify-fine.invalid`. The PSL-private cases use `fl-fixture-000{0,1,2}`. The only real-brand strings left are official domains: `test_canonical.py:15,90` and `test_url_signals.py:275,277`, plus the all-official-domains sweep. Those are acceptable under PR-5. |
| 2. Raw bidi and zero-width characters in source, ruff errors | **Resolved** | `textutil.py:11-14` and `test_url_signals.py:96,98,217` now use `\u…` escapes. `ruff --select PLE2502,PLE2515,PLE2512-2514` on the branch gives `All checks passed!`. The same check on `main` gives 5 hits in these files. `make lint` passes. |
| 3. `url.data_uri` not emitted | **Resolved, with a regression** (finding 1 below) | `obfuscation.py:29-48` adds the signal, `test_url_signals.py:81-86` tests it, and SCORING §2 line 27 has the +2.0 weight. |
| (non-blocking 5) `Evidence.error` embeds `str(exc)` | Resolved | `base.py:141` keeps only `type(exc).__name__`, and the test checks `== "RuntimeError"`. |
| (non-blocking 4) the timeout can't interrupt the sync body | Documented | `base.py:133-135` |
| (non-blocking 7) rebase, DECISIONS conflict | Resolved | `git merge-tree origin/main origin/fix/signals-url-review` exits 0. |

## Checks run (worktree `scratchpad/fl-review-9`, detached at `405c2d9`, `uv sync --all-packages`)

| Command | Result |
|---|---|
| `make test` (ruff check, ruff format --check, mypy, pytest) | exit 0. `All checks passed!`, `70 files already formatted`, mypy `Success: no issues found in 27 source files`, `311 passed, 1 skipped` |
| `uv run pytest packages/falcon_core/tests/contracts -q` | exit 0, `10 passed`. The skill's `tests/contracts` path doesn't exist; the contract tests live in the package. |
| `make eval-gate` | exit 0 but **SKIPPED**: no `evals/baseline.json` yet. That is not a pass. |
| `make scan` | exit 0. gitleaks `no leaks found`, pip-audit `No known vulnerabilities found`, trivy clean. syft isn't installed, so there's no SBOM (warning only). |
| `make guard` | exit 0 |
| `uvx ruff check --isolated --select PLE2502,PLE2515,PLE2512,PLE2513,PLE2514 packages scripts` | exit 0, `All checks passed!` |
| `grep -P` for raw U+061C, U+200B-200F, U+202A-202E, U+2060-2069, U+FEFF over `git ls-files` | Hits only in the vendored `signals/url/data/confusables.txt`, which is Unicode data and was accepted in PR-5 |
| Domain-token sweep of `tests/signals/*.py` (tokens not ending in `.test`/`.example`/`.invalid`) | Only official `adpolice.gov.ae` and `login.adpolice.gov.ae`, `example.com`, `www.wikipedia.org`, `fl-fixture-*.{github.io,ngrok-free.app,trycloudflare.com}`, `falcon-demo-bank-login.github.io` and `github.io` |
| `scratchpad/probes/pr5_probe.py` (the PR-5 probe: 18 hostile inputs × all signals, jsonschema 2020-12 against `contracts/evidence.schema.json`) | schema failures **0**, signal errors **0**, raw hosts **0** on the original input set, worst latency 15.5 ms |
| `scratchpad/probes/pr5_legit.py` over `legit_urls.csv` from `origin/feat/evals-legit-and-qwen` (410 rows) | **0** risk evidence. This is an informal probe, not an eval artifact. |
| `scratchpad/probes/pr9_datauri.py` (10 hostile `data:` inputs against `url.data_uri`) | **2 contract violations**, see finding 1 |
| `git merge-tree --write-tree origin/fix/signals-url-review origin/feat/obs-metrics` | exit 1, conflict in `DECISIONS.md` with PR #14 (finding 5) |

## Findings

### Blocking
1. **LOW-MEDIUM (contract invariant 5, evidence.schema `observed`): `url.data_uri` echoes attacker text, including raw URLs, into `observed.mime`.** At `packages/falcon_core/src/falcon_core/signals/url/obfuscation.py:37-39`, `mime` is whatever comes before the first `;` or `,`, provided it contains a `/`. Probe output:
   ```
   'data:https://evil.example/login.php,x'  -> {'mime': 'https://evil.example/login.php', ...}
   'data:text/html<script>alert(1)</script>/x,1' -> {'mime': 'text/html<script>alert(1)</script>/x', ...}
   ```
   The first one is a live, non-defanged URL in evidence, which CONTRACTS.md §invariants 5 and the `observed` description in `evidence.schema.json` ("defanged if they are URLs") forbid. The second puts markup into a field the UI will render. React escapes it, but it's still attacker text in a field documented as a MIME type.
   *Fix:* validate the type against an RFC 6838 token pattern. For example, if `re.fullmatch(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}", mime)` doesn't match, use `"invalid"`. Add these two inputs to `test_data_uri_evidence`.

### Non-blocking
2. **LOW** `obfuscation.py:44`: `"length": len(c.raw)`, but `canonical.py:274` truncates `raw` to 512, so any longer `data:` URI reports `length: 512` (probe: `'data:' + 'a/'*300` → 512). Carry the original length on `CanonicalURL`, or rename the field to `length_capped`.
3. **INFO** `test_url_signals.py:211`: the comment "r next to e on QWERTY" is stale now that the input is `bamk` (m next to n). The gov-style hyphenation case (`dubaipolice-gov.ae`) was removed without a Falcon Demo Bank replacement, such as a test-only registry entry on `falcon-demo-bank.gov.zz` as PR-5 suggested. Combosquat coverage of the `-gov` pattern is now thinner.
4. **INFO (for T-001/L1)** The project ruff config (`pyproject.toml:57`, `select = ["E","F","I","UP","B","SIM","S"]`) doesn't include `PLE2502`/`PLE2515`, so CI won't catch a regression of PR-5 finding 2. PR #14 adds new raw bidi literals, and CI didn't flag them (see `reviews/PR-14.md`). I recommend adding `"PLE25"` to `select`.
5. **INFO** PR #9 and PR #14 both append to the end of `DECISIONS.md` and conflict there. Whichever merges second needs a trivial rebase, unless the `merge=union` gitattributes branch lands first.

## Eval impact
URL signals still emit no FP risk evidence on the 410-row legit set (informal probe). `url.data_uri` now gives the arbiter its +2.0 weight on `data:` targets. Recall impact can't be measured until T-020 and T-023 exist. The eval gate is skipped (no baseline).

## Escalation
This is round 2 for T-007 URL signals (PR-5 → PR-9). Per the supervisor rules, L1 should decide: either merge after the builder pushes the finding 1 fix (I'll confirm with a re-run of `pr9_datauri.py` plus `make test`), or reassign.
