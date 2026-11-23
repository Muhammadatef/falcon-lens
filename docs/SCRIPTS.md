# Scripts and make targets, in plain language

This is the map of everything you can run in the repo. Run `make help` to see the make targets with a one-line
description. Every script also starts with a header (a docstring in Python, a comment block in shell) that says
what it does, when to use it, how to run it, what it reads and writes, and what to be careful about.

Owners come from `docs/ARCHITECTURE.md` (code ownership). "Needs the stack" means `make up` must have finished first.

Rules that apply to everything below:

- Nothing here sends a live phishing URL anywhere. Real feed rows live only under `data/private/` (gitignored).
- Never commit `.env` or anything under `data/private/`. `make guard` checks this.
- Numbers in docs and slides come from `evals/results/published/*.json`, never from the demo-metrics emitter.

## Make targets

| Target | What it is for | Command | Owner |
|---|---|---|---|
| help | Lists every target with a description | `make help` | platform |
| up | Starts the stack (core + obs) and waits until it is healthy | `make up` (needs `.env`: `cp .env.example .env`) | platform |
| down | Stops everything, keeps the data volumes | `make down` | platform |
| lint | Style and lint check (ruff); writes nothing | `make lint` | platform |
| typecheck | Static type check (mypy) | `make typecheck` | platform |
| test | Runs lint, typecheck and the pytest suite; run before every PR | `make test` | platform |
| test-web | Web checks: typecheck, eslint, vitest, build, Playwright e2e against a mock gateway | `make test-web` | frontend |
| guard | Fails if a tracked file has a live URL or sits under `data/private/` | `make guard` | platform |
| openapi | Regenerates `contracts/openapi.yaml` from the API code | `make openapi` | platform |
| smoke | End-to-end check against the running stack (starts it if needed) | `make smoke` or `FL_SMOKE_FAKE_WORKER=1 make smoke` (not a G1 pass) | platform |
| scan | Security scans (gitleaks, pip-audit, pnpm audit, trivy, SBOM); missing tools only warn | `make scan` | platform |
| seed | Fills the running stack with demo data (labelled `source=replay`) | `make seed` (`FORCE=1` to resend) | platform (demo tooling) |
| replay | Steady fake traffic and a planted Sentinel campaign | `make replay RATE=2/s DURATION=10m` | platform (demo tooling) |
| demo | Starts everything, pre-warms the models, seeds, prints URLs | `make demo` | platform (demo tooling) |
| urls | Prints the local URLs | `make urls` | platform (demo tooling) |
| tunnel | Opens a public cloudflared tunnel to the gateway | `make tunnel` | platform (demo tooling) |
| tunnel-stop | Stops that tunnel | `make tunnel-stop` | platform (demo tooling) |
| demo-reset | Deletes the demo Postgres and Redis volumes, then runs `make demo` (asks first; destructive) | `make demo-reset` (`YES=1` skips the question) | platform (demo tooling) |
| unblock | Reverts a Sentinel block | `make unblock ID=act_xxx` (needs `DATABASE_URL` and `REDIS_URL` reachable from your machine) | sentinel |
| fit-thresholds | Builds the dataset, trains the T1 classifier, writes `params.yaml` and the model | `make fit-thresholds` | evals |
| eval | Offline evaluation; writes JSON, HTML and `latest.prom` under `evals/results/` | `make eval` (needs private data) | evals |
| eval-gate | Compares the latest eval with the baseline (prints SKIPPED, which is not a pass, without private data) | `make eval-gate` | evals |
| eval-baseline | Writes `evals/baseline.json` from the latest result; review the diff | `make eval-baseline` | evals |
| redteam | Not implemented yet (exits 1) | `make redteam` | security |
| submission | Builds submission/ (fields, deck, PDF, checklist) and traces every number | `make submission` | docs |

## Scripts in `scripts/`

| Script | What it is for | Command | Owner |
|---|---|---|---|
| `check_no_live_urls.py` | The defensive-only guard behind `make guard` | `make guard` | platform |
| `check_openapi_drift.py` | Fails if the API implements a route that `contracts/openapi.yaml` does not declare | `uv run python scripts/check_openapi_drift.py` | platform |
| `gen_openapi.py` | Writes (or with `--check` verifies) `contracts/openapi.yaml` | `make openapi` | platform |
| `smoke.sh` | Wrapper for `make smoke`: starts the stack, optionally swaps in the fake worker | `make smoke` | platform |
| `smoke.py` | The eight smoke assertions | `uv run python scripts/smoke.py` (stack must be up) | platform |
| `wait_healthy.sh` | Waits until all containers are healthy | `scripts/wait_healthy.sh [seconds]` | platform |
| `urls.sh` | Prints the app, Grafana and Prometheus URLs | `scripts/urls.sh` | platform |
| `protect_main.sh` | Turns on GitHub branch protection for `main` (admin, run once) | `scripts/protect_main.sh [owner/repo]` | platform |
| `emit_demo_metrics.py` | Serves SYNTHETIC metrics so dashboards can be eyeballed | `uv run python scripts/emit_demo_metrics.py --port 9199` | observability |
| `readme_metrics.py` | Copies published eval numbers into the README block | `python scripts/readme_metrics.py [--check]` | docs |
| `qwen_task.py` | The only way to call the local model for bulk drafts; validates every item | `uv run --no-project --with httpx --with jsonschema python scripts/qwen_task.py --task ID --kind KIND --spec SPEC.json` | evals |
| `collect_loop.sh` | Polls the OpenPhish feed every 12 hours | `scripts/collect_loop.sh &` | evals |

## Demo tooling in `scripts/falcon_demo/`

Entry point: `PYTHONPATH=scripts uv run python -m falcon_demo <command>`. Normally you use the make targets above.

| Module | What it is for | Command | Owner |
|---|---|---|---|
| `__main__.py` | Dispatches `seed`, `replay`, `urls`, `next`, `prewarm`, `tunnel`, `tunnel-stop`, `reset`, `reset-state` | via `make` | platform |
| `common.py` | Shared helpers: `.env` loading, API client, Redis event sinks | library | platform |
| `corpus.py` | Decides what gets seeded; only reserved/test domains and hashes pass | library | platform |
| `seed.py` | Implements `make seed` | `make seed` | platform |
| `replay.py` | Implements `make replay` | `make replay` | platform |
| `ops.py` | Implements urls, next, prewarm, tunnel, tunnel-stop, reset | `make urls`, `make tunnel`, `make demo-reset` | platform |

## Eval tooling in `evals/`

| File | What it is for | Command | Owner |
|---|---|---|---|
| `collect/openphish.py` | Polls the OpenPhish feed; raw rows private, hashes public | `uv run --no-project --with httpx --with tldextract python evals/collect/openphish.py` | evals |
| `collect/snapshot_queue.py` | Placeholder for page snapshots (waiting on the sandbox capture endpoint) | `uv run python evals/collect/snapshot_queue.py` | evals |
| `datasets/build.py` | Builds the labelled set, the hashed manifest and the split lock | `uv run python -m evals.datasets.build` (also run by `make fit-thresholds`) | evals |
| `datasets/collect_legit_urls.py` | Refreshes the list of legitimate URLs (rarely needed) | `uv run --no-project --with httpx --with tldextract --with pyyaml python evals/datasets/collect_legit_urls.py run` | evals |
| `splits.py` | Split assignment and the frozen-test check | `uv run python -m evals.splits --check` | evals |
| `train/fit.py` | Trains and calibrates the T1 classifier, fits the thresholds | `make fit-thresholds` | evals |
| `train/pipeline.py` | Offline scoring path shared by training and eval | library | evals |
| `harness/run.py` | The evaluation run behind `make eval` | `make eval` | evals |
| `harness/metrics.py`, `harness/report.py` | Metric maths; HTML and Prometheus rendering | library | evals |
| `gate.py` | The merge gate and the baseline writer | `make eval-gate`, `make eval-baseline` | evals |

## Service entrypoints and infra

You do not run these by hand; the containers start them (`make up`).

| File | What it is for | Owner |
|---|---|---|
| `services/api/src/falcon_api/main.py` | The public API (FastAPI) | platform |
| `services/mcp/src/falcon_mcp/main.py` | MCP server skeleton (health only so far) | platform |
| `services/worker/src/falcon_worker/main.py` | Reads jobs from Redis and runs the detection cascade | agent-core |
| `services/sentinel/src/falcon_sentinel/main.py` | Watches events, opens incidents, runs triage, serves the approval API | sentinel |
| `services/sentinel/src/falcon_sentinel/unblock.py` | The code behind `make unblock` | sentinel |
| `services/egress/src/falcon_egress/main.py` | Filtering proxy that keeps the sandbox away from internal addresses | security |
| `infra/alertmanager/entrypoint.sh` | Picks the alert receiver (Telegram, webhook or none) when the container starts | observability |
| `infra/grafana/gen_dashboards.py` | Regenerates the six Grafana dashboard JSON files | observability |
| `services/sandbox/src/falcon_sandbox/main.py` | Headless-browser service: `/render` (page features) and `/capture` (snapshots) | sandbox |

The submission scripts (`scripts/submission/`, `scripts/scan.sh`) are documented in their own files by their owners.
