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

## Offline prompt optimisation (DSPy, ADR-002)

`make dspy-optimize` optimises the prompt of every shipped LLM role offline with DSPy (3.5.0): `extractor`, `investigator`, and the three Sentinel tasks `sentinel_assess`, `sentinel_summarise`, `sentinel_propose` (the responder is not optimised: user-facing reasons are template-only, D3). The metric is the production validators (router schema parse, the Sentinel verifier `vet` and evidence-id faithfulness, tool-argument validation and ProvenanceRule, caps) plus a task score on labelled synthetic data; invalid output scores 0. TRAIN optimises, VALIDATION selects; the frozen test split and the held-out legit sets are never read. A candidate is adopted for a route only if the paired bootstrap 95% CI of (after - before) on VALIDATION excludes 0; otherwise the hand-written prompt stays and the artifact says `not adopted (within noise)`. Route: `DSPY_ROUTE=cloud|local`; the default is cloud when `ANTHROPIC_API_KEY` is already in the environment, else local (Ollama). Cloud runs use the same model the router uses for that role; the key is never read from a file, printed or stored. Compiled prompts are stored per route (`prompts/compiled/<role>.<route>.json`, sha256-checked) and the router loads only the one for the route it is calling; a missing or tampered file means the hand-written prompt is used. Each run writes `evals/results/published/dspy/<role>_<sha>_<ts>.json` with before/after on VALIDATION (95% bootstrap CI), model id, DSPy version, call/token budget and seeds. Numbers on this synthetic data are not detection quality.

- **Programs** (`evals/dspy/optimize.py`, `evals/dspy/roles.py`): one DSPy Signature + `Predict` per role. The input is the router's own user turn (redacted, spotlighted, datamarked); the output is the one JSON reply. The LLM never sets a score or severity.
- **Data** (train and validation only; the frozen test split is never read): incidents from the Sentinel replay fixture generator over many seeds (train seeds 1-12, validation seeds 101-108, gold from the replayed incident which the fixture labels confirm); messages from template-generated invented text until a supervisor-approved message set is dropped into `evals/dspy/approved_messages.jsonl`. Messages are split by template, so validation templates are unseen. Both sets are synthetic and labelled so.
- **Metrics** (`evals/dspy/roles.py`, `evals/dspy/fl_metrics.py`, unit-tested): the production validators, with `falcon_sentinel.verify` shared with the triage graph, plus a task score on labelled synthetic data (extractor field accuracy, investigator useful tool choice, Sentinel verifier accept and claim coverage).
- **Optimisers**: `BootstrapFewShot` and `MIPROv2` (small trial budget). A candidate is adopted only under the CI rule above: the paired bootstrap 95% CI of (after - before) on VALIDATION must exclude 0; otherwise the hand-written prompt stays (`not adopted (within noise)`).
- **Artifact**: `evals/results/published/dspy/<role>_<sha>_<ts>.json` (before and after on validation with 95% CI, paired CI, dataset sha256, git SHA, DSPy version, model id, seeds, real calls, DSPy cache hits, tokens, duration). Cloud and local runs are separate artifacts. The Anthropic key comes from the process environment only, is never passed as a DSPy kwarg, and is never written anywhere.

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
| `sovereign/` | sovereign-mode proof (`scripts/sovereign_proof.py`): FL_SOVEREIGN_MODE=1, no cloud key, per local model: demo scenarios, voice utterance, Sentinel LLM summary, which model each role used, egress audit; failed runs are published too | synthetic fixtures, synthetic speech |

Fixtures are the invented Falcon Demo Bank on `.test` hosts, labelled as test fixtures, served only by an offline fixture renderer; no live page is visited. The red-team shipped-cascade artifact (PR #84) covers prompt injection and is not repeated here.

### Voice live bench (synthetic speech, on-site vs public tunnel)

Source: `evals/results/published/voice/voice_live_bench_<sha>_<ts>.json`, written by `evals/voice_live_bench.py`. 85 synthetic clips (macOS `say` Majed/Daniel/Samantha/Karen/Rishi at several speeds, Amazon Polly Zayd/Hala/Matthew, three synthetic noise variants), sent through the web route to the live API; the artifact labels `SYNTHETIC_SPEECH: true`.
- Synthetic speech, not real speakers: read every number as an upper bound. Local = gateway on the Mac Studio, tunnel = public `falconlens.app`; both used the native `whisper-large-v3-turbo` engine.
- Local (83 scored clips): wake 97.6%, intent 89.2%, FAQ answer 84.6%, language 100%, off-topic and injection redirected 8 of 8, round trip p50 0.26 s / p95 0.66 s; tunnel (72 scored): wake 97.2%, intent 91.7%, p50 0.96 s / p95 1.97 s.
- Tunnel pass had 13 errors in 85 requests (4 read timeouts at 30 s, 6 instant connection errors in a row, 2 HTTP 502 including the expected over-limit clip) against 2 in the local pass; the remaining failures are listed with the exact utterance and the transcript in the artifact.
- Server latency is a Prometheus histogram delta (the response carries no timing), local pass only; the rate limit (20 a minute) forces pacing of 3.3 s between requests.

### Sovereign-mode proof (what "runs fully locally" may and may not claim)

Source: `evals/results/published/sovereign/sovereign_<model>_<ts>.json`, written by `scripts/sovereign_proof.py` against an isolated stack (compose project `flsov`) with `FL_SOVEREIGN_MODE=1` and no `ANTHROPIC_API_KEY`. Four fresh-stack runs are published (2 per model), the failed ones too; one machine, invented Falcon Demo Bank fixtures, synthetic `say` speech.
- Both local models, `inkling-2-mini-chat` (Ollama) and Qwen 3.8 27B (`alibaba:qwen3.8:27b:mirai:mirai-m:4` via the :8085 gate, needs `FL_LOCAL_NO_THINK=1`), passed 7 of 7 scenarios (six demo scenarios + Sentinel scene) in every run; every LLM call in the logs has route `local` and the expected model id.
- Voice utterance passed in every run through the container faster-whisper (`faster-whisper-small`, wake + intent correct, 1.12 to 1.45 s wall time per utterance (`voice.wall_s` in the four artifacts: 1.17, 1.39, 1.12, 1.45)).
- Sentinel incident LLM summary was accepted by the faithfulness verifier in 1 of 4 runs (inkling run 2); in the other 3 the model was called but its summary was rejected and the template was used, so those 3 runs are published as `failed`. Do not claim "every Sentinel summary is written by the local model".
- Egress audit, all 4 runs. The proof is: no `ANTHROPIC_API_KEY` in any LLM service, the sovereign flag set in every one, and only route `local` in the LLM call logs and metrics. The egress proxy logged 0 destinations in these runs, so that log proves nothing on its own. The Anthropic base-URL sink counted 0 hits, but these four runs did not self-test that the sink was listening, so do not cite the 0 as evidence (the runner now records a self-test hit). This shows no LLM traffic was configured or observed to leave the machine; it is not a claim that nothing left it.
- Still needs the internet in sovereign mode: RDAP/crt.sh/IANA lookups about the checked domain, reputation feeds, the sandbox's one passive visit to the checked site, and the one-time download of the speech model weights (huggingface.co, own allow-listed proxy).
