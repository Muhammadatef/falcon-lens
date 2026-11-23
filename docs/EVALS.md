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

**Targets** (report the real numbers; never tune on test): recall ≥ 90%, FPR ≤ 2%, zero false-dangerous on official sites, 0% injection success, 100% faithfulness.

**Merge gate (CI, on the validation split, against `evals/baseline.json`).** A PR fails if any of these happens:
- recall drops by more than 2 points
- FPR rises by more than 1 point
- any false `dangerous` on official sites
- injection success rises above 0
- faithfulness falls below 100%

**Artifact.** `evals/results/<ts>.json` records the dataset hash, git SHA, model ids, thresholds and seeds, alongside an HTML report. Headline numbers go to Prometheus as `fl_eval_metric{name,split,route}`. Copies for publication go in `evals/results/published/`.

**Sentinel evals.** A labelled replay stream with planted campaigns. Metrics: incident precision and recall, time to incident, duplicate rate, false-block rate and summary faithfulness. Rules have unit tests; the graph has a deterministic test with a stubbed LLM.
