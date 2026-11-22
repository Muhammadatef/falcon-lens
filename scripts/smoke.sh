#!/usr/bin/env bash
# smoke.sh - `make smoke`: start the stack if needed, then run the end-to-end smoke test (T-015).
#
# What it does:
#   Checks that .env exists, starts the stack (core, obs and tools profiles) when the API is not healthy, waits
#   for the gateway to answer /v1/version, then runs scripts/smoke.py. Real mode (default, the G1 gate) uses
#   the REAL worker. With FL_SMOKE_FAKE_WORKER=1 it stops the real worker and starts the fake-worker TEST DOUBLE
#   (services/api/src/falcon_api/fake_worker.py); that only proves the API and SSE path, is NOT a G1 pass,
#   and the script says so loudly. On exit it stops the double and restarts the real worker.
#
# When to use it:
#   Before a PR that touches the pipeline, and before gate G1. Takes a few minutes on a cold start.
#
# How to run:
#   make smoke                              (direct: scripts/smoke.sh)
#   FL_SMOKE_FAKE_WORKER=1 make smoke       (API-only check with the test double)
#
# Inputs:
#   .env in the repo root; env COMPOSE_PROJECT_NAME (isolate parallel stacks), FL_GATEWAY_URL
#   (default https://localhost:8443), FL_SMOKE_FAKE_WORKER.
#
# Outputs / side effects:
#   May build and start Docker containers, stop and start the worker, and submits fixture checks (these
#   add rows and counters to the running stack). Exit code is that of smoke.py.
set -euo pipefail
cd "$(dirname "$0")/.."

export FL_GATEWAY_URL="${FL_GATEWAY_URL:-https://localhost:8443}"
DC=(docker compose --profile core --profile obs --profile tools)

if [[ ! -f .env ]]; then echo "Missing .env: run 'cp .env.example .env' first." >&2; exit 1; fi

api_healthy() {
  local id
  id=$("${DC[@]}" ps -q api 2>/dev/null || true)
  [[ -n "$id" && "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$id")" == "healthy" ]]
}

if ! api_healthy; then
  echo "smoke: stack not up, starting it (make up)"
  "${DC[@]}" up -d --build
  FL_PROFILES="core obs tools" scripts/wait_healthy.sh 300
fi
# fixtures live in the `tools` profile
"${DC[@]}" up -d fixtures >/dev/null

if [[ "${FL_SMOKE_FAKE_WORKER:-0}" == "1" ]]; then
  echo "################################################################"
  echo "# FL_SMOKE_FAKE_WORKER=1: a TEST DOUBLE answers jobs. Not a G1 pass. #"
  echo "################################################################"
  "${DC[@]}" stop worker >/dev/null 2>&1 || true
  "${DC[@]}" --profile smoke-fake up -d fake-worker
  trap '"${DC[@]}" --profile smoke-fake stop fake-worker >/dev/null 2>&1 || true; "${DC[@]}" start worker >/dev/null 2>&1 || true' EXIT
  sleep 2
fi

# Wait for the gateway to answer through to the API.
for _ in $(seq 1 60); do
  if curl -ksf -o /dev/null "$FL_GATEWAY_URL/v1/version"; then break; fi
  sleep 2
done

uv run python scripts/smoke.py
