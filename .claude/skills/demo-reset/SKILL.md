---
name: demo-reset
description: Reset the demo environment to a clean, seeded state.
---
# demo-reset

1. `make down && docker volume rm falcon_pgdata falcon_redisdata` (demo volumes only), then `make up`.
2. `make seed` (verdicts tagged source=replay), then check the Grafana dashboards show the REPLAY badge.
3. Pre-warm: one check of each DEMO.md scenario so the caches and the browser pool are warm.
4. Print the URLs: web, board, Grafana, API docs, and the MCP endpoint.
