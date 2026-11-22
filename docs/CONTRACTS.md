# CONTRACTS

The machine-readable sources of truth are in `contracts/`. Pydantic models in `packages/falcon_core/contracts/` are generated from them or hand-mirrored, and `tests/contracts/` round-trips both ways. Changing a contract needs an L1 edit and a version bump.

| File | Used by |
|---|---|
| `verdict.schema.json` | every surface: REST, SSE, MCP, web, extension, Telegram |
| `evidence.schema.json` | signals → arbiter → reasons |
| `signal.schema.json` | signal plugin registration (`add-signal` skill) |
| `event.schema.json` | Redis Stream `fl:events` → Sentinel |
| `incident.schema.json` | Sentinel → board, REST, MCP, STIX |
| `tools.schema.json` | investigator, Sentinel and MCP tool registry plus the JSON `Action` |
| `openapi.yaml` | REST v1. FastAPI generates it; CI checks it hasn't drifted from the committed file |

Key invariants:
1. `reasons[].evidence_ids` must reference ids in `evidence[]`.
2. `verdict` is never the word "safe".
3. `no_warning_signs` always carries `actions.caution`.
4. Degraded verdicts are never `no_warning_signs`.
5. URLs in any output are defanged.
6. Events and incidents never carry raw page or message text.

## Internal messages (API <-> worker)
Owned by builder-platform (API side) and builder-agent-core (worker side). Not public; the public contracts are the schemas above.

**Submit (API -> worker).** `XADD fl:jobs MAXLEN ~5000` with string fields:
`verdict_id` (`vd_` + ULID), `input_type` (`url|message|email|image`), `payload_json`, `submitted_at` (ISO-8601 UTC), `source` (`live|replay|synthetic|fixture`).
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

## Internal messages

### OpenPhish mirror (Redis)
- `feed:openphish` is a Redis SET of lowercase sha256 hex digests, never plaintext: the sha256 of the canonical URL
  (lowercase scheme and host, default port and fragment dropped, empty path becomes `/`; same form as the collector's
  `sha256` field) and the sha256 of the lowercase ASCII (punycode) host. Host digests are stored only for bare-path
  listings, so one phishing page on a shared host never condemns the host.
- `feed:openphish:updated_at` is the last poll time as epoch seconds (JSON number). Age = now minus this value; H2 needs age < 6 h.
- Writer: `falcon_core.signals.reputation.mirror.refresh_openphish` (periodic job, reads `data/private/feeds/openphish/2*.jsonl`, emits `feed.updated {feed, entries, age_s}` on `fl:events` as field `event` = JSON).
- Reader: signal `rep.openphish` via `FeedMirror.lookup`. The set is private and is never exported (OpenPhish terms).
