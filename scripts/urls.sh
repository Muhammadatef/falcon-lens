#!/usr/bin/env bash
# Print the local URLs of the running stack. Ports come from the environment, then .env, then defaults.
set -euo pipefail

env_or_file() { # name default
  local name="$1" default="$2" val="${!1:-}"
  if [[ -z "$val" && -f .env ]]; then
    val=$(sed -n "s/^${name}=\([0-9]*\).*/\1/p" .env | head -n1)
  fi
  echo "${val:-$default}"
}

gw=$(env_or_file FL_GATEWAY_PORT 8443)
prom=$(env_or_file FL_PROMETHEUS_PORT 9090)
graf=$(env_or_file FL_GRAFANA_PORT 3001)

echo ""
echo "Falcon Lens is up (project: ${COMPOSE_PROJECT_NAME:-falcon}):"
echo "  App        https://localhost:${gw}   (local CA: accept the certificate warning)"
echo "  Grafana    http://localhost:${graf}    (admin / \$GRAFANA_ADMIN_PASSWORD)"
echo "  Prometheus http://localhost:${prom}"
