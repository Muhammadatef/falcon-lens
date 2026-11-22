#!/usr/bin/env bash
# T-003 network acceptance (needs Docker). Builds the egress image, then runs a probe on an
# internal-only network: proxy -> metadata must give 403, direct 1.1.1.1 must have no route.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
compose=(docker compose -f "$here/compose.yml")
trap '"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
"${compose[@]}" build egress-proxy
"${compose[@]}" up --abort-on-container-exit --exit-code-from probe probe egress-proxy
