SHELL := /bin/bash
.DEFAULT_GOAL := help
COMPOSE := docker compose --profile core --profile obs
NYI = @echo "make $@: not yet implemented" >&2; exit 1

.PHONY: help up down smoke test eval redteam seed replay demo scan submission unblock

help:
	@echo "Targets: up down smoke test eval redteam seed replay demo scan submission"

up: ## Start core + obs, wait until every service is healthy
	@test -f .env || { echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; }
	$(COMPOSE) up -d --build
	@scripts/wait_healthy.sh 300
	@echo ""
	@echo "Falcon Lens is up:"
	@echo "  App        https://localhost:8443   (local CA: accept the certificate warning)"
	@echo "  Grafana    http://localhost:3001    (admin / \$$GRAFANA_ADMIN_PASSWORD)"
	@echo "  Prometheus http://localhost:9090"

down: ## Stop everything (data volumes are kept; use 'docker compose down -v' to wipe)
	docker compose --profile core --profile obs --profile tools --profile stretch down --remove-orphans

test: ## ruff + mypy (falcon_core) + pytest
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest -q

unblock: ## Revert a Sentinel block: make unblock ID=act_xxx (needs DATABASE_URL and REDIS_URL, host-reachable)
	@test -n "$(ID)" || { echo "usage: make unblock ID=act_<id>" >&2; exit 2; }
	uv run python -m falcon_sentinel.unblock $(ID)

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

smoke:
	$(NYI)
eval:
	$(NYI)
redteam:
	$(NYI)
seed:
	$(NYI)
replay:
	$(NYI)
demo:
	$(NYI)
submission:
	$(NYI)
