# OBSERVABILITY

**Stack.** OpenTelemetry SDK in every service → otel-collector, which feeds Prometheus (metrics), Loki (JSON logs, through the log shipper) and the LLM tracer (chosen in `docs/research/VERIFIED_VERSIONS.md`). Grafana uses all three. Prometheus alerts go to Alertmanager, then to Telegram or the webhook if configured.

Every log line, span and LLM span carries `verdict_id` (or `incident_id`).

**Metrics.** All use the `fl_` prefix and follow the build prompt §11 exactly; that list is the contract. The labels `source=live|replay` appear on `fl_checks_total`, `fl_incidents_total` and `fl_campaign_new_domains_total`, so dashboards can label replayed data.

**Dashboards** (`infra/grafana/dashboards/*.json`, provisioned automatically, 5 s refresh):
1. Command overview
2. Detection quality
3. Pipeline performance
4. AI operations
5. Security
6. Sentinel

Panels fed by replay data show a "REPLAY" text badge driven by `source`.

**Alerts** (`infra/prometheus/rules/*.yml`). Each rule has a `runbook_url` annotation pointing to `docs/RUNBOOK.md#<id>`.
