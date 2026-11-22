SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose --profile core --profile obs
DEMO = PYTHONPATH=scripts uv run python -m falcon_demo
NYI = @echo "make $@: not yet implemented" >&2; exit 1

.PHONY: eval-baseline fit-thresholds help up down smoke openapi test test-web eval eval-gate redteam redteam-fixtures xss seed replay demo demo-reset tunnel tunnel-stop urls unblock scan submission guard lint typecheck

help:
	@echo "Targets: up down smoke test test-web eval eval-gate redteam seed replay demo demo-reset tunnel tunnel-stop urls unblock scan submission guard"
	@echo "Parallel stacks: COMPOSE_PROJECT_NAME=x FL_GATEWAY_PORT=.. FL_PROMETHEUS_PORT=.. FL_GRAFANA_PORT=.. make up"

up: ## Start core + obs, wait until every service is healthy
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; }
	$(COMPOSE) up -d --build
	@scripts/wait_healthy.sh 300
	@scripts/urls.sh

down: ## Stop everything (data volumes are kept; use 'docker compose down -v' to wipe)
	docker compose --profile core --profile obs --profile tools --profile stretch down --remove-orphans

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run mypy

test: lint typecheck ## ruff + mypy (falcon_core) + pytest
	uv run pytest -q

test-web: ## web: typecheck + eslint + vitest + production build + Playwright e2e (mock gateway, strict CSP)
	cd web && pnpm install --frozen-lockfile && pnpm typecheck && pnpm lint && pnpm test:unit && pnpm build && pnpm test:e2e

unblock: ## Revert a Sentinel block: make unblock ID=act_xxx (needs DATABASE_URL and REDIS_URL, host-reachable)
	@test -n "$(ID)" || { echo "usage: make unblock ID=act_<id>" >&2; exit 2; }
	uv run python -m falcon_sentinel.unblock $(ID)

guard: ## defensive-only guard: no live URLs, no data/private in git
	python3 scripts/check_no_live_urls.py

# Merge gate for detection quality. Becomes real when builder-evals lands evals/baseline.json:
# until then it says so loudly and does NOT claim a pass.
eval-gate:
	uv run python -m evals.gate --run

eval-baseline: ## write evals/baseline.json from the latest result (review the diff in the PR)
	uv run python -m evals.gate --make-baseline

fit-thresholds: ## train T1 + calibrate + fit bands on train/val only; writes params.yaml and scoring/model/
	uv run python -m evals.datasets.build
	uv run python -m evals.train.fit

scan: ## gitleaks, pip-audit, pnpm audit, trivy, semgrep, compose/image hardening, syft (missing tools warn locally)
	@scripts/scan.sh

smoke: ## T-015 assertions against the running stack (starts it if needed). FL_SMOKE_FAKE_WORKER=1 uses a test double (NOT a G1 pass)
	@scripts/smoke.sh

openapi: ## Regenerate contracts/openapi.yaml from the FastAPI app (CI fails on drift)
	uv run python scripts/gen_openapi.py
eval: ## offline eval (val + test): JSON + HTML + latest.prom under evals/results/
	uv run python -m evals.harness.run
redteam: ## prompt-injection / obfuscation red-team suite; exits non-zero if attack success > 0 (FL_LIVE_LLM=1: live model)
	uv run python -m evals.redteam

redteam-fixtures: ## regenerate services/fixtures/redteam/*.html from evals/redteam/cases.yaml
	uv run python -m evals.redteam build-fixtures

xss: ## Playwright XSS check of the verdict UI with red-team strings (needs FL_WEB_URL; stub until the web app lands)
	uv run --with playwright==1.65.2 python -m evals.redteam.xss_check
submission: ## Build submission/ (form fields, deck, PDF, CHECKLIST) and trace every number. SUBMISSION_STRICT=1 fails when the MVP is not shipped
	uv run --with-requirements scripts/submission/requirements.txt python scripts/submission/build.py
	uv run --with-requirements scripts/submission/requirements.txt python scripts/submission/check_numbers.py
	uv run python scripts/submission/descriptions.py --check submission/description_en.txt submission/description_ar.txt

# ---- demo tooling (gate G6) ---------------------------------------------------------------------------
seed: ## Push the corpus through the real API/worker as source=replay (idempotent; FORCE=1 resubmits)
	$(DEMO) seed $(if $(FORCE),--force,)

replay: ## Steady labelled traffic + planted Sentinel campaign: make replay RATE=2/s DURATION=10m
	$(DEMO) replay --rate $(or $(RATE),2/s) --duration $(or $(DURATION),10m)

demo: ## up (core+obs+tools) -> healthy -> pre-warm -> seed -> print URLs
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; }
	docker compose --profile core --profile obs --profile tools up -d --build
	@FL_PROFILES="core obs tools" scripts/wait_healthy.sh 600
	@$(DEMO) prewarm
	@$(DEMO) seed || echo "WARN: seed incomplete (see above); the stack is up, re-run 'make seed' when the failing service is ready." >&2
	@$(DEMO) urls
	@$(DEMO) next

urls: ## Print the local URLs of the running stack
	@$(DEMO) urls

tunnel: ## Public cloudflared quick tunnel to the gateway; URL in data/private/tunnel_url.txt
	@$(DEMO) tunnel

tunnel-stop: ## Stop the tunnel started by `make tunnel` (other cloudflared processes are untouched)
	@$(DEMO) tunnel-stop

demo-reset: ## Reset Postgres+Redis volumes and seed state (names resolved from `docker compose config`), then `make demo`; YES=1 skips the prompt
	@YES=$(YES) $(DEMO) reset
	$(MAKE) demo

