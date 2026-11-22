# INTEGRATION: ready to connect (not connected)

Falcon Lens has **no** existing integration with Abu Dhabi Police and implies no endorsement. This page describes how a police mobile app or internal agent *could* connect. Nothing here is wired to any agency system.

## Surfaces
| Surface | Entry | Auth |
|---|---|---|
| REST v1 | `https://<host>/v1/*`, contract `contracts/openapi.yaml` (generated, drift-checked in CI) | `X-API-Key: <key>` or `Authorization: Bearer <key>` |
| MCP (streamable HTTP) | `https://<host>/mcp`, registered in `.mcp.json` | `Authorization: Bearer $FL_MCP_BEARER_TOKEN` |
| Webhooks (outbound) | targets in `FL_WEBHOOK_TARGETS` | HMAC-SHA256 signature |
| STIX 2.1 | `GET /v1/intel/stix` | key with `intel` scope |

Check endpoints (`/v1/check/*`, `/v1/reports`, `/v1/feedback`) also work anonymously with a per-IP limit (the public PWA uses this). A key that is presented but wrong gets `401`, never silent anonymous access.

## Keys, scopes, limits
Keys are stored only as argon2id hashes (peppered with `FL_API_KEY_PEPPER`). Scopes: `check` (submit checks), `read` (verdicts, campaigns, incidents), `intel` (STIX), `operator` (approve/reject held Sentinel actions). Each key has its own per-minute rate limit; `429` carries `Retry-After`. Create one with `scripts/create_api_key.py --label NAME --scopes check,read --rate-limit 120` (printed once). Every keyed call is written to the append-only `api_audit_log` table (key id, method, path, status, request id, a keyed hash of the caller IP; never bodies). `UPDATE`, `DELETE` and `TRUNCATE` are revoked and blocked by triggers. The public sandbox key (`FL_SANDBOX_API_KEY`, scopes `check`+`read`, 30 req/min) is seeded at start-up.

Errors are RFC 9457 `application/problem+json`; they never echo submitted content. Lists use cursors: `?limit=&cursor=` returns `{items, next_cursor}`. Writes accept `Idempotency-Key`.

## Endpoints in one glance
`POST /v1/check/{url,message,email,image}` · `GET /v1/verdicts/{id}[/events]` · `POST /v1/reports` · `POST /v1/feedback` · `GET /v1/campaigns` + `/stream` · `GET /v1/incidents` + `/stream` + `/{id}` · `POST /v1/incidents/{id}/actions/{action_id}/approve|reject` (operator) · `GET /v1/intel/stix` · `GET /v1/meta`. Examples: `docs/api/curl-examples.md`; Postman collection: `docs/api/falcon-lens.postman_collection.json`; typed client: `clients/python/falcon_lens_client.py`.

## MCP tools
`check_url`, `check_message`, `check_email`, `get_verdict`, `list_campaigns`, `list_incidents`, `get_incident`, `submit_report`. They call the REST API with a service key limited to `check`+`read`, so MCP can never approve an action or export intel. Returned text is data, not instructions. `.mcp.json` expands `${FL_MCP_BEARER_TOKEN}` and optional `${FL_MCP_URL:-https://localhost:8443/mcp}`.

## Webhooks
For campaign incidents the API POSTs `{"event":"campaign.alert","id":...,"data":<campaign>}` to each target. Headers: `X-Falcon-Timestamp` (unix seconds), `X-Falcon-Signature: v1=<hex>` where hex = HMAC-SHA256(`FL_WEBHOOK_SECRET`, `<timestamp>.<raw body>`), `X-Falcon-Delivery`. Receivers must verify in constant time and reject timestamps more than 300 s from their clock (replay window); `verify_webhook` in the Python client does both. Failed deliveries are retried twice with back-off.

## Data crossing the boundary
- **In:** URL, message text, `.eml`, or image for a check; report/feedback with SHA-256 hashes only. Report text is stored only when the caller sets `consent_store_text=true`.
- **Out:** verdicts (reasons cite evidence ids, URLs defanged), campaign cards and incidents (defanged indicators, aggregate counts), STIX indicators. Never raw page or message text, never personal data of reporters. Replayed or synthetic data carries `source` labels.
- Caveat: with a cloud model route, structured evidence (not raw content) is what the model sees; see `docs/PRIVACY.md`.

## Sovereign mode
`FL_SOVEREIGN_MODE=true` forces every model call to the local model; no content leaves the machine. The API and MCP behave identically, and `GET /v1/meta` reports `sovereign_mode` so a client can show it. Feeds that need external keys stay off unless configured.

## Parallel stack
`COMPOSE_PROJECT_NAME=falcon-mcp FL_GATEWAY_PORT=18443 FL_PROMETHEUS_PORT=19090 FL_GRAFANA_PORT=13001 make up` runs a second isolated stack (own volumes, networks, host ports).
