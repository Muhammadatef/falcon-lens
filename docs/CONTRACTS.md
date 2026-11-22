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
