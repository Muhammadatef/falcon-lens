# PR-5 review: feat(signals): T-007 URL/lexical signals + brand registry

- Former PR #5 · local branch `keep/feat/signals-url` · head `ca4316e`
- Task: T-007 (builder-signals, P0) · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22
- L1 decisions applied (DECISIONS "SCORING updates from PR #5 and #7", SCORING §6): typosquat length tiers, `tld_swap` at 0.8 and confidence scaling are **accepted**, so I didn't block on them. `url.data_uri` +2.0 is now in SCORING §2 (see finding 3).
- The GitHub repo is being recreated, so this was reviewed from the local branch only. No `gh` posting.

## Verdict: **CHANGES REQUESTED**

The signal logic is good. All evidence validates against `contracts/evidence.schema.json`, hosts in `observed` and `display` are defanged, and there were no errors on adversarial input. On the 411-row legit set, the URL signals emitted no risk evidence. Three things block the merge: test fixtures that imitate real UAE brands on real TLDs, raw bidi and zero-width control characters in source files, and the `url.data_uri` evidence that L1 accepted but the PR doesn't emit. The PR also claims "ruff clean", which doesn't reproduce.

## Checks run (worktree `scratchpad/fl-review-5`, detached at `ca4316e`)

| Command | Result |
|---|---|
| `PYTHONPATH=packages/falcon_core/src uv run --no-project --with pytest --with pyyaml --with tldextract pytest packages/falcon_core/tests/signals -q` | exit 0, `55 passed in 0.21s` |
| `uvx ruff check --isolated --config 'lint.isort.known-first-party=["falcon_core"]' packages/falcon_core` (ruff 0.17.3) | **exit 1, `Found 20 errors`**. Besides I001, they are: `SIM905` at `brands/registry.py:18,26`, `url/lexical.py:18`, `url/obfuscation.py:94`, `url/squatting.py:27`; `PIE810` at `obfuscation.py:116`; `SIM114` at `squatting.py:78`; **`PLE2502`/`PLE2515` at `url/textutil.py:11,13` and `tests/signals/test_url_signals.py:87,89,188`** |
| `cd packages/falcon_core && MYPYPATH=src uv run --no-project --with mypy --with types-PyYAML --with pyyaml --with tldextract mypy --strict --explicit-package-bases src` | exit 0, `Success: no issues found in 14 source files` |
| `gitleaks git . --no-banner` | exit 0, no leaks |
| `git merge-tree --write-tree main keep/feat/signals-url` | **exit 1**, conflict in `DECISIONS.md` |
| Contract and defang probe `scratchpad/probes/pr5_probe.py` (18 inputs × 10 signals, including 4 KB URLs, 150 query params, RLO, data:, javascript:, empty; jsonschema Draft 2020-12 against `contracts/evidence.schema.json`) | schema failures **0**; raw (non-defanged) hosts in observed/display **0**; signal errors **0**; observed strings > 512 chars **0**; worst single-signal latency 14 ms |
| `scratchpad/probes/pr5_legit.py` over `evals/datasets/legit_urls.csv` from PR-8 (411 rows, excluding `url.lexical_features`) | **0 risk evidence** on all 411 rows (an informal probe, not an eval artifact) |
| Domain-like tokens in the test diff that aren't `.test`/`.example` | `adpolicr.com`, `adpolice.com`, `dubaipolice-gov.ae`, `adpolice.gov.ae.verify-fine.xyz`, `abc123.ngrok-free.app`, `abc.trycloudflare.com`, `someuser.github.io`, `falcon-demo-bank-login.github.io`, `www.wikipedia.org`, `example.com` (finding 1) |
| Image or binary files | none (`confusables.txt` is the vendored Unicode text file, and its licence is noted) |

## Findings

### Blocking
1. **MEDIUM (defensive-only): fixtures imitate real brands on live TLDs.** CLAUDE.md says "Fixtures use only the invented brand Falcon Demo Bank", and the PR body says "reserved `.test`/`.example` hosts only". But `tests/signals/test_url_signals.py:130` (`adpolice.gov.ae.verify-fine.xyz`), `:178` (`adpolicr.com`), `:179` (`adpolice.com`), `:181` (`dubaipolice-gov.ae`) and `:226` (`adpolice.com`) commit lookalikes of Abu Dhabi Police and Dubai Police on registrable public TLDs. I did not resolve them, so whether any of them is live or malicious is unknown. That uncertainty is the reason the rule exists in a public repo. This is the same standard as PR-2 finding 5 (`x.gov.ae`).
   *Fix:* test the tiers against Falcon Demo Bank through a test-only registry (`FALCON_BRANDS_YAML` fixture or `ctx.brands`). For example, give it a second verified domain on a never-delegated multi-label suffix such as `falcon-demo-bank.gov.zz` for the gov-style typosquat and hyphenation cases, and use `falcon-demo-bank.example` for `tld_swap`. Keep the real-brand tests that only check **official** domains (`smartservices.adpolice.gov.ae`, `login.adpolice.gov.ae`, the sweep over all brands.yaml domains): those aren't imitations. The PSL-private cases (`*.github.io`, `*.ngrok-free.app`, `*.trycloudflare.com`) need real suffixes and are acceptable, but use clearly invented labels such as `fl-fixture-0000`.
2. **LOW (gate/hygiene): raw bidi and zero-width control characters in source.** ruff `PLE2502` ("Contains control characters that can permit obfuscated code") flags `url/textutil.py:11` and `tests/signals/test_url_signals.py:87,188`, and `PLE2515` flags a raw ZWSP at `textutil.py:13:31` and `test_url_signals.py:89:58`. In a public security repo, Trojan-Source-style raw controls are exactly what reviewers can't see. *Fix:* write them as `‮`, `​` and so on. Also fix the other ruff errors listed above (`ruff check --fix` handles most of them) and correct the PR body's "ruff clean" claim. Add `# noqa: RUF001` only on the deliberate Cyrillic and Arabic confusable literals, if T-001 enables RUF.
3. **LOW (SCORING conformance): `url.data_uri` isn't emitted.** L1 accepted `url.data_uri` +2.0 (SCORING §2, DECISIONS "SCORING updates from PR #5 and #7"). The registry has 10 signals and none is `url.data_uri`. A `data:text/html;base64,…` input produces no evidence (probe), so the arbiter can never apply the weight. *Fix:* add a `url.data_uri` signal (family `url`, observed `{"mime": …, "base64": bool, "length": n}`, never the payload), plus tests.

### Non-blocking
4. **LOW** `signals/base.py:118-122`: `asyncio.wait_for` can't interrupt the sync body (`inner()` never awaits), so the 50 ms `timeout_ms` is never enforced. Inputs are capped at 4 KB, and the worst case I measured was 14 ms, so the risk is low. Document it, or enforce the URL length cap before calling the body.
5. **LOW** `base.py:126`: `Evidence.error` embeds `str(exc)`, which can carry fragments of the attacker URL. Keep only `type(exc).__name__`, or defang it.
6. **INFO (eval impact)**: one homograph input fires `url.homograph` (1.0) **and** `url.typosquat` (1.0) **and** `url.combosquat` (0.5) (probe: `fаlcon-demo-bank.test`). That stacks about +6.5 log-odds. It's acceptable as draft weights, but T-022 should check for double counting.
7. Rebase on `main`. `DECISIONS.md` conflicts. Drop the "Proposals for L1" line, because L1 already decided it.

## Eval impact
On the legit set there is no FP risk evidence from URL signals (probe above). Recall impact can't be measured until T-020 and T-023 exist.
