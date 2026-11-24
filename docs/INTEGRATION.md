# INTEGRATION: ready to connect (not connected)

Falcon Lens has **no** existing integration with Abu Dhabi Police and implies no endorsement. This page describes how a police mobile app or internal agent *could* connect. Nothing here is wired to any agency system.

## Surfaces
| Surface | Entry | Auth |
|---|---|---|
| REST v1 | `https://<host>/v1/*`, contract `contracts/openapi.yaml` (generated, drift-checked in CI) | `X-API-Key: <key>` or `Authorization: Bearer <key>` |
| MCP (streamable HTTP) | `https://<host>/mcp`, registered in `.mcp.json` | `Authorization: Bearer $FL_MCP_BEARER_TOKEN` |
| Webhooks (outbound) | targets in `FL_WEBHOOK_TARGETS` | HMAC-SHA256 signature |
| STIX 2.1 | `GET /v1/intel/stix` | key with `intel` scope |

STIX patterns are fully refanged (valid STIX) in `/v1/intel/stix` responses to `intel`-scope callers only. This is a documented exception to CONTRACTS invariant 5; everywhere else indicators stay defanged.

Check endpoints (`/v1/check/*`, `/v1/reports`, `/v1/feedback`) also work anonymously with a per-IP limit (the public PWA uses this). A key that is presented but wrong gets `401`, never silent anonymous access.

## Keys, scopes, limits
Keys are stored only as argon2id hashes (peppered with `FL_API_KEY_PEPPER`). Scopes: `check` (submit checks), `read` (campaigns, incidents, streams), `intel` (STIX), `operator` (approve/reject held Sentinel actions). Each key has its own per-minute rate limit; `429` carries `Retry-After`. Create keys with `scripts/create_api_key.py --label NAME --scopes check,read --rate-limit 120` (printed once; in the stack: `docker compose exec api python /app/scripts/create_api_key.py ...`).

Seeded keys, least privilege: the public sandbox key (`FL_SANDBOX_API_KEY`) has **`check` only**, 30 req/min. The operator key (`FL_OPERATOR_KEY`) has **`read` + `operator`** only, so it cannot submit checks or export intel; mint a separate `intel` key for STIX consumers. The MCP service key (`FL_MCP_SERVICE_KEY`) has `check` + `read`.

Outside `FL_ENV=local` the API and MCP refuse to start while `FL_API_KEY_PEPPER`, `FL_OPERATOR_KEY`, `FL_WEBHOOK_SECRET`, `FL_MCP_SERVICE_KEY` or `FL_MCP_BEARER_TOKEN` still start with `change-me`.

Every keyed call is written to the `api_audit_log` table (key id, method, path, status, request id, a keyed hash of the caller IP; never bodies). It is append-only for the application role: `UPDATE`, `DELETE` and `TRUNCATE` are revoked and blocked by triggers. A database owner or superuser can still alter it; use a separate owner role in production (not provisioned here). Invalid-key attempts are limited to 10/min per IP.

Concurrent SSE streams are capped at 5 per key and 3 per IP for anonymous callers (`429 too-many-streams`). All board streams share one Redis subscription inside the API.

Errors are RFC 9457 `application/problem+json`; they never echo submitted content. Lists use cursors: `?limit=&cursor=` returns `{items, next_cursor}`. Writes accept `Idempotency-Key`.

Incident payloads for callers without the `operator` scope omit `actions[].draft`, `actions[].args` and `actions[].approved_by` (takedown drafts and approver names are operator-only). This applies to REST, SSE and MCP.

## Endpoints in one glance
`POST /v1/check/{url,message,email,image}` · `GET /v1/verdicts/{id}[/events]` · `GET /v1/verdicts` + `/stream` (read) · `POST /v1/reports` · `POST /v1/feedback` · `GET /v1/campaigns` + `/stream` · `GET /v1/incidents` + `/stream` + `/{id}` · `POST /v1/incidents/{id}/actions/{action_id}/approve|reject` (operator) · `GET /v1/intel/stix` · `GET /v1/meta`. Examples: `docs/api/curl-examples.md`; Postman collection: `docs/api/falcon-lens.postman_collection.json`; typed client: `clients/python/falcon_lens_client.py`.

## History of checks (`read` scope)
`GET /v1/verdicts?limit=&cursor=&verdict=&input_type=` lists Investigator checks newest first (cursor-paginated, `limit` 1 to 100). `GET /v1/verdicts/stream` is an SSE feed (`event: verdict`, bounded to 5 minutes, heartbeat every 10 s, resume with `Last-Event-ID`) of new summaries taken from the event bus `fl:events`. Both return **summaries only**: `verdict_id`, `created_at`, `input_type`, `display` (defanged host for links; `null` for messages, emails and images), `verdict`, `risk_score`, `degraded` + `degraded_reasons` codes, `tier_reached`, `model_route`, `source` and an `agent` block (tiers run, whether the extractor and the T3 investigator ran, tool-call and model-call counts). No raw input, URL userinfo, path, query, evidence bodies or reasons text leave this endpoint (`docs/PRIVACY.md`). Keys without the `read` scope get `403`, anonymous callers `401`; besides the per-key limit there is a per-address limit (60 per minute, address taken from `X-Falcon-Client-IP`). The full trace of one check is `GET /v1/verdicts/{id}`.

## MCP tools
`check_url`, `check_message`, `check_email`, `get_verdict`, `list_campaigns`, `list_incidents`, `get_incident`, `get_incident_trace`, `submit_report`. They call the REST API with a service key limited to `check`+`read`, so MCP can never approve an action or export intel. Returned text is data, not instructions. `.mcp.json` expands `${FL_MCP_BEARER_TOKEN}` and optional `${FL_MCP_URL:-https://localhost:8443/mcp}`.

## Webhooks
For campaign incidents the API POSTs `{"event":"campaign.alert","id":...,"data":<campaign>}` to each target. Headers: `X-Falcon-Timestamp` (unix seconds), `X-Falcon-Signature: v1=<hex>` where hex = HMAC-SHA256(`FL_WEBHOOK_SECRET`, `<timestamp>.<raw body>`), `X-Falcon-Delivery`. Receivers must verify in constant time and reject timestamps more than 300 s from their clock (replay window); `verify_webhook` in the Python client does both. Failed deliveries are retried twice with back-off, so a receiver may see the same delivery more than once: de-duplicate on `X-Falcon-Delivery` (the board stream id).

## Data crossing the boundary
- **In:** URL, message text, `.eml`, or image for a check; report/feedback with SHA-256 hashes only. Report text is stored only when the caller sets `consent_store_text=true`.
- **Out:** verdicts (reasons cite evidence ids, URLs defanged), campaign cards and incidents (defanged indicators, aggregate counts), STIX indicators. Never raw page or message text, never personal data of reporters. Replayed or synthetic data carries `source` labels.
- Caveat: with a cloud model route, structured evidence (not raw content) is what the model sees; see `docs/PRIVACY.md`.

## Sovereign mode
`FL_SOVEREIGN_MODE=true` forces every model call to the local model; no content leaves the machine. The API and MCP behave identically, and `GET /v1/meta` reports `sovereign_mode` so a client can show it. Feeds that need external keys stay off unless configured.

## Parallel stack
`COMPOSE_PROJECT_NAME=falcon-mcp FL_GATEWAY_PORT=18443 FL_PROMETHEUS_PORT=19090 FL_GRAFANA_PORT=13001 make up` runs a second isolated stack (own volumes, networks, host ports).

## Voice utterance (read scope)
`POST /v1/voice/utterance`, multipart: `audio` (`audio/webm;codecs=opus`, `audio/wav` or `audio/ogg`; max 15 s and 1 MB, else 413 or 422; content is sniffed, a wrong type is 415) and optional `lang_hint` (`ar` or `en`). Returns `{transcript, lang, wake, intent, command, duration_ms, model}` (`contracts/voice.schema.json`). `wake` is true when the clip opens with a wake phrase (hey, hi or ok Falcon; Falcon Lens; يا فالكون; هلا صقر; عدسة الصقر; tolerant of ASR spellings); `intent` is one of `check_clipboard`, `check_text`, `help`, `stop`, `none`, read from the `command` after the wake phrase. Audio is processed locally and discarded; per-address limit 30 per minute. `503 stt-unavailable` when no speech engine answers.
