#!/usr/bin/env bash
# Wait until every container of the falcon project (selected profiles) is running and healthy.
# Usage: scripts/wait_healthy.sh [timeout_seconds]   (default 300)
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
