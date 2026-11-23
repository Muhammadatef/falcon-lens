#!/usr/bin/env bash
# wait_healthy.sh - block until every container of the stack is running and healthy.
#
# What it does:
#   Every 3 seconds it lists the containers of the selected compose profiles with `docker compose ps`,
#   inspects their state and health, and exits 0 once all are running and healthy. If the timeout passes it
#   prints which services are not ready and exits 1.
#
# When to use it:
#   Right after `docker compose up -d`. `make up`, `make demo` and scripts/smoke.sh call it for you.
#
# How to run:
#   scripts/wait_healthy.sh [timeout_seconds]              (default 300; no make target)
#   FL_PROFILES="core obs tools" scripts/wait_healthy.sh 600
#
# Inputs:
#   Optional first argument (timeout) and env FL_PROFILES (default "core obs"). Needs Docker.
#
# Outputs / side effects:
#   Read-only: prints progress and the final status; it never starts or stops containers.
set -euo pipefail

TIMEOUT="${1:-300}"
PROFILES="${FL_PROFILES:-core obs}"
args=()
for p in $PROFILES; do args+=(--profile "$p"); done

deadline=$((SECONDS + TIMEOUT))
while true; do
  ids=$(docker compose "${args[@]}" ps -q)
  bad=()
  for id in $ids; do
    name=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$id")
    state=$(docker inspect -f '{{.State.Status}}' "$id")
    health=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id")
    if [[ "$state" != "running" ]]; then bad+=("$name($state)"); continue; fi
    if [[ "$health" != "healthy" ]]; then bad+=("$name($health)"); fi
  done
  if [[ -z "$ids" ]]; then bad+=("no containers"); fi
  if [[ ${#bad[@]} -eq 0 ]]; then
    echo "All services healthy."
    exit 0
  fi
  if (( SECONDS >= deadline )); then
    echo "Timed out after ${TIMEOUT}s waiting for: ${bad[*]}" >&2
    docker compose "${args[@]}" ps >&2 || true
    exit 1
  fi
  sleep 3
done
