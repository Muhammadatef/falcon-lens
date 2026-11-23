# DSPy prompt optimisation (offline, ADR-002)

Optimises the prompt of every shipped LLM role: `extractor`, `investigator`, `sentinel_assess`,
`sentinel_summarise`, `sentinel_propose`. Production never imports `dspy`; it loads frozen JSON.

## Cloud run (owner)

Load the key into the shell without printing it, then run from the main checkout:

    set -a; . /path/to/.env; set +a
    make dspy-optimize DSPY_ROUTE=cloud

Each role runs on the same Anthropic model the router uses for it in production, capped at 300 real LM calls.
The script never reads a dotenv file, never prints or stores the key, and keeps the DSPy cache in the gitignored
`work/dspy_cache`.

Outputs to commit:

- `packages/falcon_core/src/falcon_core/prompts/compiled/<role>.cloud.json` (only for roles that were adopted)
- `evals/results/published/dspy/<role>_<sha>_<ts>.json` (one report per role, adopted or not)
- `evals/dspy/tests/recorded/<role>.cloud.json` (5 recorded replies for the loader tests, adopted roles only)

Local (Ollama) run: `make dspy-optimize DSPY_ROUTE=local`. Files are per route, and a prompt compiled on one route is
never loaded on the other.

## Adoption rule

A compiled prompt is adopted for a route only if the paired bootstrap 95% CI of (after - before) on VALIDATION
excludes 0. Otherwise nothing is written (a stale file for that role and route is deleted), the report says
`not adopted (within noise)`, and production keeps the hand-written prompt.

## Metric

The production validators (`falcon_core.llm.router` parse, `falcon_sentinel.verify`, `ToolRegistry.validate`) plus a
task score on labelled synthetic data. See `roles.py`. TRAIN optimises, VALIDATION selects; the frozen test split
is never read.
