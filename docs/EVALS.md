# EVALS

Data lives under `data/`. Live URLs, snapshots and logos are in `data/private/`, which is gitignored. Manifests with hashes and defanged URLs are committed.

| Set | Target | Source |
|---|---|---|
| phishing URLs | ≥300 | OpenPhish community (and other feeds if keys arrive), with first_seen and a sandbox snapshot taken at collection |
| legit URLs | ≥300, including ≥100 hard negatives | verified UAE gov and bank pages, popular sites, real login and payment pages, new legitimate domains, shortened legitimate links |
| zero-day | ≥40 | phishing not on any enabled blocklist at collection, plus Falcon Demo Bank fixtures |
| messages | ≥150 | Gulf Arabic, MSA, English and Arabizi; real public examples where licensing allows, plus tagged synthetic |
| emails | ≥40 | fictional `.eml` |
| injection | ≥50 | local fixtures (`evals/redteam/`); `make redteam` = reference pipeline, `make redteam-shipped` = shipped cascade with a real model (artifact `published/redteam/redteam_shipped_<sha>_<ts>.json`) |

**Splits.** Temporal cut (every test first_seen is later than every train first_seen) and grouping by registrable domain, so no domain appears in two splits. The test split is frozen and its sha256 is in `evals/splits.lock`. All tuning happens on validation.

**Post-freeze items.** The test split never grows. An item or domain that first appears after the freeze is assigned only to train or validation (deterministically, whole domains together); a new item on a domain already in test is excluded and counted. The build report and `evals/splits.lock` carry a `post_freeze` count, and `test_sha256` stays byte-identical.

**Metrics.** Bootstrap 95% confidence intervals (1000 resamples) for precision, recall, F1, FPR and PR-AUC; reliability curve and ECE; false `dangerous` on verified-official sites; zero-day recall vs the blocklist-only baseline; ablation by signal family; latency p50/p95 per tier; cost per check; share of checks reaching an LLM; faithfulness; injection attack success rate; flip rate over 3 runs; Arabic clarity (judged by a model other than the generator, calibrated on 20 items the owner rated). Cloud and sovereign routes are reported separately, and real and synthetic data are reported separately.

**Held-out legitimate sets (`heldout_legit*.csv`, `scripts/fp_regress.py`).** Sets 1 and 2 were inspected while the sandbox budget and payload rules were being fixed, so any figure measured on them after those fixes is **post-hoc** (fit to the set it is measured on) and must be labelled so. Set 3 (a fresh seeded Tranco draw, disjoint from sets 1 and 2, `legit_urls.csv` and every split) was used only for a single measurement with the rules frozen; its artifact is the unseen number. Each artifact flags items read only partially (`partial`) and counts them (`partial_reads`).

**Targets** (report the real numbers; never tune on test): recall ≥ 90%, FPR ≤ 2%, zero false-dangerous on official sites, 0% injection success, 100% faithfulness.

**Merge gate (CI, on the validation split, against `evals/baseline.json`).** A PR fails if any of these happens:
- recall drops by more than 2 points
- FPR rises by more than 1 point
- any false `dangerous` on official sites
- injection success rises above 0
- faithfulness falls below 100%

**Artifact.** `evals/results/<ts>.json` records the dataset hash, git SHA, model ids, thresholds and seeds, alongside an HTML report. Headline numbers go to Prometheus as `fl_eval_metric{name,split,route}`. Copies for publication go in `evals/results/published/`.

**Sentinel evals.** A labelled replay stream with planted campaigns. Metrics: incident precision and recall, time to incident, duplicate rate, false-block rate and summary faithfulness. Rules have unit tests; the graph has a deterministic test with a stubbed LLM.

### Shipped-cascade red-team: how to quote it
`make redteam-shipped` writes `coverage_caveat` into its artifact. Never quote the harmful count without it: the number is
"harmful at extended local-model deadlines (model answered N of 113)", and "at production deadlines the model answered M of 113
(timeouts) with the same harmful cases". The figures live only in `evals/results/published/redteam/` (one artifact per budget);
copy them from there, never from this page. Eight extra `t3_page` cases (uncertain band, so the T3 investigator runs) are
reported separately as `summary.t3_uncertain` and are not part of the 113.

Recipe (two runs, the second embeds the first one's coverage in its caveat; extended investigator deadline 300 s, harness only):
```
make redteam-shipped BUDGET=production PUBLISH=1
make redteam-shipped BUDGET=extended PAIRED=evals/results/published/redteam/<production artifact>.json PUBLISH=1
```

**Gap-closing evals** (`python -m evals.gaps <area>`, raw runs from `python -m evals.gaps.jobs`). Each area writes one artifact under `evals/results/published/<area>/` (never at the top level, which belongs to the main eval artifact the README and the web page read). Every artifact states scope, n, the CI method, data provenance, model route and model ids, and the git SHA; anything it could not measure stays `not_evaluated` with the reason.

| Area (folder) | What it measures | Data |
|---|---|---|
| `synthetic_split/` | real and synthetic items scored apart (the frozen manifest has zero synthetic items), provenance of every published metric family | real val/test, synthetic fixtures |
| `faithfulness/` | template reasons cite evidence that is in the verdict and say what the evidence says (checker R1 to R4, mutation-tested); Sentinel LLM summaries: verifier accept rate and claim to evidence coverage, local and cloud | real val/test offline, synthetic fixtures and replay |
| `stability/` | 3 repeat runs of the shipped cascade, AI layers on: label agreement and score variance per tier, with an AI-off control | synthetic fixtures |
| `route_compare/` | cloud (Anthropic API) against local (sovereign) route on the same inputs: verdict agreement, extractor field accuracy, latency p50 and p95, tokens | synthetic fixtures |
| `cost_per_check/` | cloud cost per check from tokens actually used times list prices (source and date inside); local route zero marginal API cost, energy not measured | synthetic fixtures |
| `sandbox_t2/` | T2 render health on held-out legit domains (recorded live-stack runs), T2 contribution on fixtures; phishing-side recall not evaluated (no labelled snapshots) | real legit, synthetic fixtures |
| `brand_new_pages/` | detection of new lookalike fixtures on hosts absent from every feed and from training | synthetic fixtures |
| `t3_investigator/` | forbidden tool calls (must be 0), step budget, label change against the run without T3, only on runs that reach the uncertain band | synthetic fixtures |
| `arabic_clarity/` | 30-item Arabic rating sheet (`rating_sheet.csv`) and automated phone-fit and reading-level checks; the human result stays `pending_human_rating` until `--ingest` of a filled sheet | shipped templates |

Fixtures are the invented Falcon Demo Bank on `.test` hosts, labelled as test fixtures, served only by an offline fixture renderer; no live page is visited. The red-team shipped-cascade artifact (PR #84) covers prompt injection and is not repeated here.
