# CONTRACTS

The machine-readable sources of truth are in `contracts/`. Pydantic models in `packages/falcon_core/contracts/` are generated from them or hand-mirrored, and `tests/contracts/` round-trips both ways. Changing a contract needs an L1 edit and a version bump.

| File | Used by |
|---|---|
| `verdict.schema.json` | every surface: REST, SSE, MCP, web, extension, Telegram |
| `evidence.schema.json` | signals → arbiter → reasons |
| `signal.schema.json` | signal plugin registration (`add-signal` skill) |
| `event.schema.json` | Redis Stream `fl:events` → Sentinel |
| `incident.schema.json` | Sentinel → board, REST, MCP, STIX. Timeline entries carry `what` (compat) plus optional bilingual `what_ar` / `what_en` |
| `campaign.schema.json` | `GET /v1/campaigns`, SSE `/v1/campaigns/stream` (projection of an incident; computed by the API; `brand_name {ar,en}` resolved from `data/brands.yaml`, never the raw brand_id) |
| `agent_trace.schema.json` | `GET /v1/incidents/{id}/trace`, MCP `get_incident_trace`, web `/incidents/[id]`: the Sentinel agent's run trace per incident (nodes, tools, model route, tokens, human-approval wait). Template fields only: no prompts, no model output, no raw text, defanged hosts. Approver and decision are operator-scope only |
| `tools.schema.json` | investigator, Sentinel and MCP tool registry plus the JSON `Action` |
| `voice.schema.json` | `POST /v1/voice/utterance` response: transcript, wake flag, intent, command (see "Voice" below) |
| `openapi.yaml` | REST v1. FastAPI generates it; CI checks it hasn't drifted from the committed file |

Key invariants:
1. `reasons[].evidence_ids` must reference ids in `evidence[]`.
2. `verdict` is never the word "safe".
3. `no_warning_signs` always carries `actions.caution`.
4. Degraded verdicts are never `no_warning_signs`.
5. URLs in any output are defanged. **One exception (L1 decision):** `GET /v1/intel/stix` returns fully refanged indicator values inside STIX patterns (valid STIX 2.1) and only to callers with the `intel` scope. Incidents, campaigns, MCP and the board stay defanged.
6. Events and incidents never carry raw page or message text.

## Internal messages (API <-> worker)
Owned by builder-platform (API side) and builder-agent-core (worker side). Not public; the public contracts are the schemas above.

**Submit (API -> worker).** `XADD fl:jobs MAXLEN ~5000` with string fields:
`verdict_id` (`vd_` + ULID), `input_type` (`url|message|email|image`), `payload_json`, `submitted_at` (ISO-8601 UTC), `source` (`live|replay|synthetic|fixture`), and optionally `channel` (`web|extension|api|mcp|voice`).
`payload_json` by type:
- `url`: `{"url": "<as submitted, trimmed>", "canonical_sha256": "<hex>"}`. The API's canonicalisation is for keying only; the worker re-canonicalises and runs the SSRF guard.
- `message`: `{"text": "...", "sha256": "<hex>"}` (max 8 KB UTF-8).
- `email` / `image`: `{"blob_key": "fl:blob:<verdict_id>", "size": N, "sha256": "<hex>"[, "mime": "image/png|jpeg|webp"]}`. The bytes are base64 in Redis string `fl:blob:<verdict_id>` (TTL 600 s). The worker deletes it after reading.

Also written by the API at submit time: `fl:job:<verdict_id>` = input fingerprint (TTL 1 h; existence means "known id"), `sf:<fingerprint>` = verdict_id (single-flight, NX, TTL 120 s), and the cache `vc:<fingerprint>` = verdict_id (TTL 24 h dangerous / 1 h suspicious / 6 h no_warning_signs), which the API fills when it observes a final verdict. The worker may fill `vc:` too, with the same value shape.

**Progress (worker -> API).** For every tier completion the worker does both, in this order:
1. `SET fl:verdict:last:<verdict_id> <verdict JSON> EX 3600` (latest known partial; lets late SSE clients replay);
2. `PUBLISH fl:verdict:<verdict_id> <verdict JSON>`.
The JSON is a full `verdict.schema.json` document with `final` set. Exactly one message has `final: true`, and it is sent last.

**Final (worker -> store).** Before the final PUBLISH the worker upserts Postgres `verdicts (verdict_id text PRIMARY KEY, doc jsonb NOT NULL, created_at timestamptz DEFAULT now())`, `doc` being the final verdict JSON. The API only reads this table (`SELECT doc ... WHERE verdict_id = $1`) and treats a missing table as "not found yet".

**Redaction.** The API sets `screenshot_url` to `null` for callers without a valid key, so the worker may always include it.

**Events (worker -> Sentinel).** After the final PUBLISH the worker emits one `verdict.created` per final verdict: `XADD fl:events MAXLEN ~ 100000 * event <json>`, a single field named `event` whose value is the full PlatformEvent JSON (`contracts/event.schema.json`). The Sentinel reads exactly that field. Payload: `{verdict, risk_score, input_type, registrable_domain (defanged), brand_id, fingerprints{dom_simhash, favicon_hash, script_embedding_id, asn, registrar, cert_issuer, registered_at}, top_signals[], tier_reached, degraded[, channel]}`. Unknown fingerprints are `null`. Never raw page or message text.

**Channel (client marker).** `POST /v1/check/url|message` accept an optional body field `channel` (`web|extension|api|mcp|voice`; anything else is 422). It rides the job (`channel` stream field), is written onto the verdict document (`verdict.schema.json` `channel`), the `verdict.created` payload and `GET /v1/verdicts` summaries, and the Sentinel lists the set of channels of an incident's linked checks (`incident.schema.json` `channels`). It is client-asserted metadata: it never changes a verdict, and an identical input answered from the verdict cache keeps the channel of the first check. The worker counts voice-initiated finals in `fl_voice_checks_total{verdict}`.

**Worker-side keys.** Consumer group `workers` on `fl:jobs`. `fl:wsf:<fingerprint>` = leader verdict_id (worker single-flight, NX, TTL 120 s): a follower waits for the leader's final in `fl:verdict:last:` and re-issues it under its own id. `fl:wclaim:<verdict_id>` = stream entry id (idempotency, TTL 300 s). Malformed jobs go to `fl:jobs:dead` and are acked. The worker fills `vc:<fingerprint>` only for non-degraded finals. Postgres `evidence` (one row per evidence item of a final verdict) is worker-internal.

## Internal messages (feeds)

### OpenPhish mirror (Redis)
- `feed:openphish` is a Redis SET of lowercase sha256 hex digests, never plaintext: the sha256 of the canonical URL
  (lowercase scheme and host, default port and fragment dropped, empty path becomes `/`; same form as the collector's
  `sha256` field) and the sha256 of the lowercase ASCII (punycode) host. Host digests are stored only for bare-path
  listings, so one phishing page on a shared host never condemns the host.
- `feed:openphish:updated_at` is the last poll time as epoch seconds (JSON number). Age = now minus this value; H2 needs age < 6 h.
- Writer: `falcon_core.signals.reputation.mirror.refresh_openphish` (periodic job, reads `data/private/feeds/openphish/2*.jsonl`, emits `feed.updated {feed, entries, age_s}` on `fl:events` as field `event` = JSON).
- Reader: signal `rep.openphish` via `FeedMirror.lookup`. The set is private and is never exported (OpenPhish terms).

## Voice
`voice.schema.json` is the response of `POST /v1/voice/utterance` (scope `read`; multipart `audio` plus optional `lang_hint` and `follow_up`). Pydantic mirror: `falcon_core.contracts.voice.VoiceUtterance`. The API-to-engine call (`POST /stt`, raw audio in, `{text, lang, ms, duration_ms, model}` out) is internal, like the worker messages. The `model` field is `<engine>:<model>` where engine is `native` or `container`. `intent` is `check_clipboard` for anything about messages, links, emails, the clipboard, scams or "run Falcon Lens"; `check_text` when the user names the text itself to check ("check this text"); `help`; `stop`; else `none`. Without the wake phrase `command` is empty and only a short bare stop word gives `stop`.
