SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose --profile core --profile obs
DEMO = PYTHONPATH=scripts uv run python -m falcon_demo

.PHONY: batch voice-e2e demo-mode-check demo-mode-on demo-mode-off voice-rehearsal redteam-shipped regress-legit eval-baseline fit-thresholds help up down smoke openapi test test-web eval eval-gate redteam redteam-fixtures xss seed replay demo demo-reset tunnel tunnel-stop urls unblock scan submission guard lint typecheck ci-local ci-local-pr dspy-optimize

help: ## List every make target with a one-line description (this list)
	@echo "Usage: make <target>   (details for every script: docs/SCRIPTS.md)"
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'
	@echo "Parallel stacks: COMPOSE_PROJECT_NAME=x FL_GATEWAY_PORT=.. FL_PROMETHEUS_PORT=.. FL_GRAFANA_PORT=.. make up"

up: ## Start core + obs, wait until every service is healthy
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; }
	@python3 scripts/ensure_local_secrets.py .env
	$(COMPOSE) up -d --build
	@scripts/wait_healthy.sh 300
	@scripts/urls.sh

down: ## Stop everything (data volumes are kept; use 'docker compose down -v' to wipe)
	docker compose --profile core --profile obs --profile tools --profile stretch down --remove-orphans

lint: ## ruff check + ruff format --check over the whole repo (writes nothing)
	uv run ruff check .
	uv run ruff format --check .

typecheck: ## mypy over the typed packages (configured in pyproject.toml)
	uv run mypy

test: lint typecheck ## ruff + mypy (falcon_core) + pytest
	uv run pytest -q

test-web: ## web: typecheck + eslint + vitest + production build + Playwright e2e (mock gateway, strict CSP)
	cd web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm lint && pnpm test:unit && pnpm build && pnpm test:e2e

unblock: ## Revert a Sentinel block: make unblock ID=act_xxx (needs DATABASE_URL and REDIS_URL, host-reachable)
	@test -n "$(ID)" || { echo "usage: make unblock ID=act_<id>" >&2; exit 2; }
	uv run python -m falcon_sentinel.unblock $(ID)

dspy-optimize: ## offline DSPy prompt optimisation for every LLM role (ADR-002). DSPY_ROUTE=cloud|local; default cloud if ANTHROPIC_API_KEY is already in the environment, else local (Ollama)
	uv run --group dspy python evals/dspy/optimize.py $(if $(DSPY_ROUTE),--route $(DSPY_ROUTE),) $(ARGS)

guard: ## defensive-only guard: no live URLs, no data/private in git
	python3 scripts/check_no_live_urls.py
	python3 scripts/check_env_example.py
	uv run python scripts/readme_stack.py --check

# Merge gate for detection quality. Becomes real when builder-evals lands evals/baseline.json:
# until then it says so loudly and does NOT claim a pass.
eval-gate: ## merge gate: latest eval vs evals/baseline.json (SKIPPED, not a pass, without private data)
	uv run python -m evals.gate --run
	@uv run python -m evals.message_text.run | sed 's/^/[report-only, not in baseline] /'

eval-baseline: ## write evals/baseline.json from the latest result (review the diff in the PR)
	uv run python -m evals.gate --make-baseline

fit-thresholds: ## train T1 + calibrate + fit bands on train/val only; writes params.yaml and scoring/model/
	uv run python -m evals.datasets.build
	uv run python -m evals.train.fit

scan: ## gitleaks, pip-audit, pnpm audit, trivy, semgrep, compose/image hardening, syft (missing tools warn locally)
	@scripts/scan.sh

smoke: ## T-015 assertions against the running stack (starts it if needed). FL_SMOKE_FAKE_WORKER=1 uses a test double (NOT a G1 pass)
	@scripts/smoke.sh

regress-legit: ## false-positive gate: 30 random held-out legit URLs through the running stack (LIVE=1, FL_GATEWAY_URL); writes evals/results/published artifact
	@test "$(LIVE)" = 1 || { echo "regress-legit needs a running stack: LIVE=1 make regress-legit" >&2; exit 2; }
	uv run python scripts/fp_regress.py

openapi: ## Regenerate contracts/openapi.yaml from the FastAPI app (CI fails on drift)
	uv run python scripts/gen_openapi.py
eval: ## offline eval (val + test): JSON + HTML + latest.prom under evals/results/
	uv run python -m evals.harness.run
	uv run python -m evals.message_text.run  # message-text eval, val only, report-only (--publish adds the frozen test split)
batch: ## check a URL list against the running API: make batch FILE=urls.txt [OUT=results.csv] [CONCURRENCY=4] [MODE=strict|lenient]
	@test -n "$(FILE)" || { echo "usage: make batch FILE=urls.txt [OUT=results.csv] [CONCURRENCY=4] [MODE=strict|lenient]"; exit 2; }
	uv run python scripts/batch_check.py "$(FILE)" --out "$(or $(OUT),results.csv)" --concurrency "$(or $(CONCURRENCY),4)" --mode "$(or $(MODE),strict)"
redteam: ## prompt-injection / obfuscation red-team suite; exits non-zero if attack success > 0 (FL_LIVE_LLM=1: live model)
	uv run python -m evals.redteam

redteam-shipped: ## same cases through the shipped cascade, real local model (BUDGET=production|extended, PAIRED=<other artifact>, ROUTE=cloud needs ANTHROPIC_API_KEY; PUBLISH=1 writes evals/results/published/redteam/)
	uv run python -m evals.redteam --pipeline shipped --route $(or $(ROUTE),local) --budget $(or $(BUDGET),production) $(if $(PAIRED),--paired-with $(PAIRED),) $(if $(PUBLISH),--publish,)

redteam-fixtures: ## regenerate services/fixtures/redteam/*.html from evals/redteam/cases.yaml
	uv run python -m evals.redteam build-fixtures

xss: ## Playwright XSS check of the verdict UI with red-team strings (needs FL_WEB_URL; stub until the web app lands)
	uv run --with playwright==1.65.2 python -m evals.redteam.xss_check
submission: ## Build submission/ (form fields, deck, PDF, CHECKLIST) and trace every number. SUBMISSION_STRICT=1 fails when the MVP is not shipped
	uv run --with-requirements scripts/submission/requirements.txt python scripts/submission/build.py
	uv run --with-requirements scripts/submission/requirements.txt python scripts/submission/check_numbers.py
	uv run python scripts/submission/descriptions.py --check submission/description_en.txt submission/description_ar.txt
	uv run --no-project --with-requirements submission/build/requirements.txt --with pyyaml python submission/build/build_all.py

# ---- demo tooling (gate G6) ---------------------------------------------------------------------------
seed: ## Push the corpus through the real API/worker as source=replay (idempotent; FORCE=1 resubmits)
	$(DEMO) seed $(if $(FORCE),--force,)

replay: ## Steady labelled traffic + planted Sentinel campaign: make replay RATE=2/s DURATION=10m
	$(DEMO) replay --rate $(or $(RATE),2/s) --duration $(or $(DURATION),10m)

demo: ## up (core+obs+tools) -> healthy -> pre-warm -> seed -> URLs -> run the six scenarios + Sentinel scene (exit 1 on any FAIL)
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; }
	@python3 scripts/ensure_local_secrets.py .env
	docker compose --profile core --profile obs --profile tools up -d --build
	@FL_PROFILES="core obs tools" scripts/wait_healthy.sh 600
	@$(DEMO) prewarm
	@$(DEMO) seed || echo "WARN: seed incomplete (see above); the stack is up, re-run 'make seed' when the failing service is ready." >&2
	@$(DEMO) urls
	@$(DEMO) next
	@$(DEMO) scenarios

demo-mode-check: ## Read-only READY / NOT READY board for the live demo (exit 0 only when READY)
	@uv run python scripts/demo_mode.py check

demo-mode-on: ## Lists what would be paused; acts only with CONFIRM=yes; then pre-warms and checks
	@uv run python scripts/demo_mode.py on $(if $(filter yes,$(CONFIRM)),--yes,)

demo-mode-off: ## Restore exactly what demo-mode-on paused (idempotent)
	@uv run python scripts/demo_mode.py off

voice-rehearsal: ## Speak the demo lines with `say`, POST to /v1/voice/utterance, put 3 messages on the clipboard
	@uv run python scripts/demo_mode.py rehearsal

urls: ## Print the local URLs of the running stack
	@$(DEMO) urls

tunnel: ## Public cloudflared quick tunnel to the gateway; URL in data/private/tunnel_url.txt
	@$(DEMO) tunnel

tunnel-stop: ## Stop the tunnel started by `make tunnel` (other cloudflared processes are untouched)
	@$(DEMO) tunnel-stop

demo-reset: ## Reset Postgres+Redis volumes and seed state (names resolved from `docker compose config`), then `make demo`; YES=1 skips the prompt
	@YES=$(YES) $(DEMO) reset
	$(MAKE) demo

# ---- local worker (Ollama only, no hosted models): docs/LOCAL_WORKER.md
LW_LABEL := ae.falconlens.localworker
LW_PLIST := $(HOME)/Library/LaunchAgents/$(LW_LABEL).plist

.PHONY: local-worker-install local-worker-uninstall local-worker-status local-worker-enqueue local-worker-run
local-worker-run: ## run the local worker in the foreground (Ctrl-C to stop)
	uv run python -m scripts.local_worker run
local-worker-install: ## render + load the launchd agent (macOS): runs 24/7, survives reboots
	@mkdir -p work/queue "$(HOME)/Library/LaunchAgents"
	@sed -e "s|@REPO@|$(CURDIR)|g" -e "s|@UV@|$$(command -v uv)|g" -e "s|@HOME@|$(HOME)|g" infra/local_worker/$(LW_LABEL).plist > "$(LW_PLIST)"
	@plutil -lint "$(LW_PLIST)"
	-@launchctl bootout gui/$$(id -u)/$(LW_LABEL) 2>/dev/null
	launchctl bootstrap gui/$$(id -u) "$(LW_PLIST)"
	@echo "installed $(LW_LABEL); check with: make local-worker-status"
local-worker-uninstall: ## stop and unload the launchd agent, then delete its plist
	-launchctl bootout gui/$$(id -u)/$(LW_LABEL)
	@test -n "$(LW_PLIST)" && rm -f "$(LW_PLIST)"
local-worker-status: ## queue counts, heartbeat, last results
	@uv run python -m scripts.local_worker status
	@launchctl print gui/$$(id -u)/$(LW_LABEL) 2>/dev/null | grep -E "state|pid" | head -3 || echo "launchd: agent not loaded"
local-worker-enqueue: ## make local-worker-enqueue KIND=summarize INPUT=path [PARAMS='{"k":1}']
	@test -n "$(KIND)" || { echo "usage: make local-worker-enqueue KIND=<kind> INPUT=<repo path>" >&2; exit 2; }
	uv run python -m scripts.local_worker enqueue --kind $(KIND) $(if $(INPUT),--input $(INPUT)) $(if $(PARAMS),--params '$(PARAMS)')


# ---- native voice STT (Mac, Metal GPU): docs/RUNBOOK.md "Voice assistant"
VOICE_PORT ?= 8093
.PHONY: voice-native voice-native-stop voice-native-status voice-bench
voice-native: ## start the native Whisper STT (mlx-whisper, 127.0.0.1:8093) in the background; pid + log under work/voice-native/
	@scripts/voice_native.sh start
voice-native-stop: ## stop the native voice STT started by `make voice-native`
	@scripts/voice_native.sh stop
voice-native-status: ## is the native voice STT up and warm?
	@curl -fsS --max-time 3 http://127.0.0.1:$(VOICE_PORT)/readyz && echo || echo "voice-native not ready (log: work/voice-native/voice-native.log)"
voice-e2e: ## LIVE end-to-end of "Hey Falcon" with a real browser against a running stack (macOS `say`); BASE_URL, PROM_URL, PHOENIX_URL; writes reviews/VOICE-E2E-<date>.md
	uv run python scripts/voice_e2e.py $(if $(LANGS),--langs $(LANGS),)
voice-bench: ## synthetic (macOS say) latency + wake accuracy for running engines; ENGINES="native=http://127.0.0.1:8093 container=http://127.0.0.1:18094"
	uv run python scripts/voice_bench.py $(foreach e,$(or $(ENGINES),native=http://127.0.0.1:$(VOICE_PORT)),--engine $(e))

ci-local: ## run every ci.yml job locally in parallel (logs: work/ci-local/<sha>/); JOBS="lint test" for a subset
	@python3 scripts/ci_local.py

ci-local-pr: ## ci-local on the merge result of origin/main + PR (temp worktree), comments on the PR: make ci-local-pr PR=123
	@test -n "$(PR)" || { echo "usage: make ci-local-pr PR=<number>" >&2; exit 2; }
	@python3 scripts/ci_local.py --pr $(PR)
