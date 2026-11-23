#!/usr/bin/env bash
# urls.sh - print the local URLs of the running stack.
#
# What it does:
#   Prints the app, Grafana and Prometheus addresses. Each port comes from the environment first
#   (FL_GATEWAY_PORT, FL_GRAFANA_PORT, FL_PROMETHEUS_PORT), then from .env, then defaults 8443, 3001 and 9090.
#
# When to use it:
#   When you forgot which port a service is on. `make up` and `make demo` already call it at the end.
#
# How to run:
#   make urls                       (the Makefile target uses the Python version; direct: scripts/urls.sh)
#
# Inputs:
#   Optional env vars above and .env in the current directory.
#
# Outputs / side effects:
#   Prints to the terminal only. Starts nothing and does not check that the services are up.
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
