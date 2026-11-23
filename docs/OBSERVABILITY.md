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
- Dashboard detail: `llm_calls_total{role,route,outcome}`, `llm_call_seconds{role,route}` (histogram), `llm_results_total{role,status}` (status fallback = the caller's template was used), `hard_rule_fired_total{rule,effect}`, `evidence_total{signal}`, `sandbox_renders_total{outcome}`, `agent_tool_calls_total{tool,status}`, `degraded_reasons_total{reason}`, `queue_depth{stream,state}` (gauge)
- Sentinel: `incidents_total{type,severity,source}`, `incident_open{severity}` (gauge), `rule_fired_total{rule}`, `time_to_incident_seconds` (histogram), `sentinel_actions_total{action,mode}`, `approvals_pending` (gauge), `blocks_reverted_total`, `event_lag_seconds` (gauge), `sentinel_dead_letter_total`, `sentinel_node_seconds{node}` (histogram), `sentinel_llm_calls_total{task,outcome}`, `sentinel_llm_seconds{task}` (histogram), `sentinel_text_total{task,generated_by}`, `approval_turnaround_seconds{decision}` (histogram), `incident_status{status}` (gauge), `sentinel_requeue_failures_total`

Helpers live in `packages/falcon_core/telemetry/metrics.py` (owned by builder-observability). Services import them and never declare their own `fl_` metrics. The labels `source=live|replay` appear on `fl_checks_total`, `fl_incidents_total` and `fl_campaign_new_domains_total`, so dashboards can label replayed data.

**Outside the contract list above** (rendered by other processes, not by the shared registry): `api_jobs_enqueued_total{input_type}` (API), `egress_connects_total{result}` (egress proxy), `stage_latency_seconds` also carries `stage="total"` (the whole check; it feeds the SLO rules). Eval artifacts are served by `services/evals-exporter` (read-only over `evals/results/published/**`; stdlib, non-root, /healthz /readyz /metrics): `eval_metric{metric,split,source,artifact,provenance}` (note: its own label set, not the registry gauge above), `eval_ci_low` / `eval_ci_high` / `eval_n` (same labels), `eval_artifact_timestamp{source,artifact}`, `eval_artifact_latest{source,artifact}`, `eval_artifact_info{source,artifact,git_sha,created_at,provenance,dataset_hash}`. Sources: `main` (T1 + arbiter), `fp_regress`, `redteam`, `message_text`, `dspy`, `fits`.

**Dashboards** (`infra/grafana/dashboards/*.json`, provisioned automatically, 5 s refresh):
1. Command overview
2. Detection quality
3. Pipeline performance
4. AI operations
5. Security
6. Sentinel
7. Model quality (`fl-model-quality`): offline eval metrics with 95% CI, n and provenance, from published artifacts only

Panels fed by replay data show a "REPLAY" text badge driven by `source`. Every panel has an `EN | AR` title, units, a description that states the threshold rationale and what "No data" means, and a runbook link where an alert exists. Regenerate with `uv run python infra/grafana/gen_dashboards.py`; recording rules are in `infra/prometheus/rules/falcon-kpi.yml`.

**Alerts** (`infra/prometheus/rules/*.yml`). Each rule has a `runbook_url` annotation pointing to `docs/RUNBOOK.md#<id>`.
