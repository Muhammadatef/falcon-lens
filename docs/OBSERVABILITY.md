# OBSERVABILITY

**Stack.** OpenTelemetry SDK in every service → otel-collector, which feeds Prometheus (metrics), Loki (JSON logs, through the log shipper) and the LLM tracer (chosen in `docs/research/VERIFIED_VERSIONS.md`). Grafana uses all three. Prometheus alerts go to Alertmanager, then to Telegram or the webhook if configured.

Every log line, span and LLM span carries `verdict_id` (or `incident_id`).

**Metrics (the contract; all prefixed `fl_`):**
- Checks: `checks_total{input_type,verdict,tier,route,source}`, `stage_latency_seconds{stage}` (histogram), `escalations_total{from,to}`, `cache_hits_total{layer}`
- Health: `tool_errors_total{tool,reason}`, `sandbox_timeouts_total`, `feed_age_seconds{feed}`, `feed_enabled{feed}` (0 or 1), `degraded_total`
- LLM: `llm_tokens_total{model,role}`, `llm_cost_usd_total{model}`, `llm_fallback_total{role}`, `route_agreement_ratio`, `agent_steps` (histogram), `canary_leak_total`
- Security: `injection_detected_total`, `ssrf_blocked_total{reason}`, `rate_limited_total{scope}`, `auth_failures_total`
- Brands and feedback: `campaign_new_domains_total{brand,source}`, `brand_impersonation_total{brand}`, `user_feedback_total{type}`
- Evals: `eval_metric{name,split,route}` (gauge, from the latest eval artifact), `score_drift_index` (gauge)
- Sentinel: `incidents_total{type,severity,source}`, `incident_open{severity}` (gauge), `rule_fired_total{rule}`, `time_to_incident_seconds` (histogram), `sentinel_actions_total{action,mode}`, `approvals_pending` (gauge), `blocks_reverted_total`, `event_lag_seconds` (gauge), `sentinel_dead_letter_total`

Helpers live in `packages/falcon_core/telemetry/metrics.py` (owned by builder-observability). Services import them and never declare their own `fl_` metrics. The labels `source=live|replay` appear on `fl_checks_total`, `fl_incidents_total` and `fl_campaign_new_domains_total`, so dashboards can label replayed data.

**Dashboards** (`infra/grafana/dashboards/*.json`, provisioned automatically, 5 s refresh):
1. Command overview
2. Detection quality
3. Pipeline performance
4. AI operations
5. Security
6. Sentinel

Panels fed by replay data show a "REPLAY" text badge driven by `source`.

**Alerts** (`infra/prometheus/rules/*.yml`). Each rule has a `runbook_url` annotation pointing to `docs/RUNBOOK.md#<id>`.

**Agent traces (Arize Phoenix).** Every service installs an OTLP exporter at start (`create_app`) when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Spans go to the otel-collector, which drops probe spans, deletes prompt/output attributes, adds the Phoenix bearer key and forwards to Phoenix (login required, UI on `127.0.0.1:${FL_PHOENIX_PORT:-6006}`, data in the `phoenix_data` volume). Span tree: `http <METHOD>` (API) and `cascade.url` > `cascade.T0..T3` > `tool.sandbox_render`, `llm.<role>`, `investigator.run` > `llm.investigator` / `tool.<name>`; Sentinel: `sentinel.triage` > `sentinel.<node>` > `llm.sentinel`. LLM spans carry OpenInference (`llm.*`) and GenAI (`gen_ai.*`) names plus `fl.llm.role`, `fl.llm.route`, `fl.latency_ms`, token counts and `verdict_id` / `incident_id`. Never recorded: prompts, model output, page text, URLs, exception messages. Setup and reset steps: `.env.example`.
