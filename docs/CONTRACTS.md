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

## Internal messages

### OpenPhish mirror (Redis)
- `feed:openphish` is a Redis SET of lowercase sha256 hex digests, never plaintext: the sha256 of the canonical URL
  (lowercase scheme and host, default port and fragment dropped, empty path becomes `/`; same form as the collector's
  `sha256` field) and the sha256 of the lowercase ASCII (punycode) host. Host digests are stored only for bare-path
  listings, so one phishing page on a shared host never condemns the host.
- `feed:openphish:updated_at` is the last poll time as epoch seconds (JSON number). Age = now minus this value; H2 needs age < 6 h.
- Writer: `falcon_core.signals.reputation.mirror.refresh_openphish` (periodic job, reads `data/private/feeds/openphish/2*.jsonl`, emits `feed.updated {feed, entries, age_s}` on `fl:events` as field `event` = JSON).
- Reader: signal `rep.openphish` via `FeedMirror.lookup`. The set is private and is never exported (OpenPhish terms).
