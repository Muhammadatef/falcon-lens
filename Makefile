SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose --profile core --profile obs
DEMO = PYTHONPATH=scripts uv run python -m falcon_demo
PROJECT = $${COMPOSE_PROJECT_NAME:-falcon}
NYI = @echo "make $@: not yet implemented" >&2; exit 1

.PHONY: help up down smoke openapi test eval eval-gate redteam seed replay demo demo-reset tunnel tunnel-stop urls unblock scan submission guard lint typecheck

help:
	@echo "Targets: up down smoke test eval eval-gate redteam seed replay demo demo-reset tunnel tunnel-stop urls unblock scan submission guard"
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

guard: ## defensive-only guard: no live URLs, no data/private in git
	python3 scripts/check_no_live_urls.py

# Merge gate for detection quality. Becomes real when builder-evals lands evals/baseline.json:
# until then it says so loudly and does NOT claim a pass.
eval-gate:
	@if [ ! -f evals/baseline.json ]; then \
	  echo "eval-gate: SKIPPED - evals/baseline.json does not exist yet (eval harness not landed). This is NOT a pass."; \
	  echo "::notice title=eval-gate skipped::no evals/baseline.json yet; detection quality is not gated"; \
	else $(MAKE) eval; fi

scan: ## gitleaks, pip-audit, pnpm audit, trivy, syft (a missing tool only warns locally)
	@rc=0; \
	if command -v gitleaks >/dev/null; then gitleaks git --config .gitleaks.toml --no-banner . || rc=1; \
	else echo "WARN: gitleaks not installed (brew install gitleaks); skipped" >&2; fi; \
	uv export --frozen --no-dev --all-packages --no-emit-workspace --no-hashes -o /tmp/falcon-requirements.txt >/dev/null \
	  && uvx pip-audit -r /tmp/falcon-requirements.txt --no-deps --disable-pip || rc=1; \
	if command -v pnpm >/dev/null; then (cd web && pnpm audit --prod) || rc=1; \
	else echo "WARN: pnpm not installed; skipped pnpm audit" >&2; fi; \
	if command -v trivy >/dev/null; then trivy fs --scanners vuln,secret,misconfig --severity HIGH,CRITICAL --exit-code 1 --skip-dirs web/node_modules --skip-dirs .venv . || rc=1; \
	else echo "WARN: trivy not installed (brew install trivy); skipped" >&2; fi; \
	if command -v syft >/dev/null; then mkdir -p evals/results && syft dir:. -q -o cyclonedx-json=evals/results/sbom.cdx.json; \
	else echo "WARN: syft not installed (brew install syft); SBOM skipped" >&2; fi; \
	exit $$rc

smoke: ## T-015 assertions against the running stack (starts it if needed). FL_SMOKE_FAKE_WORKER=1 uses a test double (NOT a G1 pass)
	@scripts/smoke.sh

openapi: ## Regenerate contracts/openapi.yaml from the FastAPI app (CI fails on drift)
	uv run python scripts/gen_openapi.py
eval:
	$(NYI)
redteam:
	$(NYI)
submission:
	$(NYI)

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

demo-reset: ## Reset Postgres+Redis volumes and seed state, then `make demo` (YES=1 skips the prompt)
	@if [ "$(YES)" != 1 ]; then read -r -p "Delete volumes $(PROJECT)_pg_data and $(PROJECT)_redis_data? [y/N] " a; [ "$$a" = y ] || { echo aborted; exit 1; }; fi
	docker compose --profile core --profile obs --profile tools --profile stretch down --remove-orphans
	docker volume rm -f $(PROJECT)_pg_data $(PROJECT)_redis_data
	$(DEMO) reset-state
	$(MAKE) demo

unblock: ## Revert a Sentinel block: make unblock ID=act_xxx (needs falcon_sentinel.unblock, host-reachable DATABASE_URL/REDIS_URL)
	@test -n "$(ID)" || { echo "usage: make unblock ID=act_<id>" >&2; exit 2; }
	@uv run python -c "import falcon_sentinel.unblock" 2>/dev/null || { echo "make unblock: falcon_sentinel.unblock not available yet (sentinel-graph PR unmerged)" >&2; exit 1; }
	uv run python -m falcon_sentinel.unblock $(ID)
