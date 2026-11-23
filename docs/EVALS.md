# EVALS

Data lives under `data/`. Live URLs, snapshots and logos are in `data/private/`, which is gitignored. Manifests with hashes and defanged URLs are committed.

| Set | Target | Source |
|---|---|---|
| phishing URLs | ≥300 | OpenPhish community (and other feeds if keys arrive), with first_seen and a sandbox snapshot taken at collection |
| legit URLs | ≥300, including ≥100 hard negatives | verified UAE gov and bank pages, popular sites, real login and payment pages, new legitimate domains, shortened legitimate links |
| zero-day | ≥40 | phishing not on any enabled blocklist at collection, plus Falcon Demo Bank fixtures |
| messages | ≥150 | Gulf Arabic, MSA, English and Arabizi; real public examples where licensing allows, plus tagged synthetic |
| emails | ≥40 | fictional `.eml` |
| injection | ≥50 | local fixtures (`evals/redteam/`) |

**Splits.** Temporal cut (every test first_seen is later than every train first_seen) and grouping by registrable domain, so no domain appears in two splits. The test split is frozen and its sha256 is in `evals/splits.lock`. All tuning happens on validation.

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

## Offline prompt optimisation (DSPy, ADR-002)

`make dspy-optimize` optimises the prompt of every shipped LLM role offline with DSPy (3.5.0): `extractor`, `investigator`, and the three Sentinel tasks `sentinel_assess`, `sentinel_summarise`, `sentinel_propose` (the responder is not optimised: user-facing reasons are template-only, D3). The metric is the production validators (router schema parse, the Sentinel verifier `vet` and evidence-id faithfulness, tool-argument validation and ProvenanceRule, caps) plus a task score on labelled synthetic data; invalid output scores 0. TRAIN optimises, VALIDATION selects; the frozen test split and the held-out legit sets are never read. A candidate is adopted only if it beats the hand-written prompt on VALIDATION. Route: `DSPY_ROUTE=cloud|local`; the default is cloud when `ANTHROPIC_API_KEY` is already in the environment, else local (Ollama). Cloud runs use the same model the router uses for that role; the key is never read from a file, printed or stored. Compiled prompts are stored per route (`prompts/compiled/<role>.<route>.json`, sha256-checked) and the router loads only the one for the route it is calling; a missing or tampered file means the hand-written prompt is used. Each run writes `evals/results/published/dspy/<role>_<sha>_<ts>.json` with before/after on VALIDATION (95% bootstrap CI), model id, DSPy version, call/token budget and seeds. Numbers on this synthetic data are not detection quality.

- **Programs** (`evals/dspy/fl_programs.py`): `IncidentSummary` (evidence view in; `summary_en`, `summary_ar`, `claims[{text_en, evidence_ids}]`, `severity` echo, `severity_reason` out) and `ScamScriptClassifier` (redacted message, features and nearest-script labels in; `script_category`, `is_scam` out). The LLM never sets severity: the metric only checks the echo.
- **Data** (train and validation only; the frozen test split is never read): incidents from the Sentinel replay fixture generator over many seeds (train seeds 1-12, validation seeds 101-108, gold from the replayed incident which the fixture labels confirm); messages from template-generated invented text until a supervisor-approved message set is dropped into `evals/dspy/approved_messages.jsonl`. Messages are split by template, so validation templates are unseen. Both sets are synthetic and labelled so.
- **Metrics** (`evals/dspy/fl_metrics.py`, unit-tested): faithfulness (every cited id exists and the text names only rule ids and domains the evidence holds; stricter than the production verifier), key-fact coverage, Arabic present, no "safe"/"آمن", length limits; classifier accuracy and per-class F1.
- **Optimisers**: `BootstrapFewShotWithRandomSearch` and `MIPROv2` (light). The best of {seed, optimiser outputs} on validation is exported, so "after" is never worse than "before".
- **Artifact**: `evals/results/dspy-<ts>.json` (before and after on validation, dataset sha256, git SHA, DSPy version, LM ids, seeds, duration, estimated cost). Cloud and local runs are reported as separate artifacts. The Anthropic key comes from the process environment (or `FL_ENV_FILE`), is never passed as a DSPy kwarg, and is never written anywhere.
