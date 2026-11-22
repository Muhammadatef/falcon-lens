# PR-6 review: feat(sentinel) LangGraph triage agent, Redis consumer, Postgres persistence, tools

- GitHub PR #6 (new repo) · branch `feat/sentinel-graph` · head `e8bcec5` · merges cleanly into `origin/main`
- **round 1 of 2** · reviewer: supervisor (L2) · 2026-11-22. The file is named `PR-6-sentinel-graph.md` so it doesn't overwrite the old skeleton review in `reviews/PR-6.md`.
- Worktree: `/tmp/fl-review-sentinel-graph`, set up with `uv sync --all-packages`. Throwaway Postgres container `fl-review-pg6` on 127.0.0.1:55439, removed after the run.

## Verdict: **CHANGES REQUESTED**

A lot of this is solid:
- the graph shape, the Postgres checkpointer and restart-resume (verified on real Postgres)
- `interrupt()` before any external draft; approval only flips a status and nothing is ever sent
- the DLQ after 3 failures, and the provenance and allowlist checks on LLM-proposed actions
- the LLM view is structured only, and the STIX 2.1 bundle shape is correct

Three defects block the merge.

## Checks run

| Command | Result |
|---|---|
| `uv sync --all-packages && make test` | exit 0. ruff `All checks passed!`, format `83 files already formatted`, mypy `Success: no issues found in 30 source files` (falcon_core only; `services/sentinel/src` isn't in mypy scope, as the PR says), pytest `332 passed, 4 skipped in 16.58s` |
| `uv run pytest -q -rs services/sentinel` | `108 passed, 3 skipped`. The 3 skips are `test_postgres_integration.py` (`FL_TEST_PG_DSN not set`) |
| `FL_TEST_PG_DSN=postgresql://falcon:testpw@127.0.0.1:55439/falcon_test uv run pytest -q services/sentinel/tests/test_postgres_integration.py` (postgres:16-alpine) | `3 passed`. Restart-resume with `AsyncPostgresSaver` across new pools works (only `propose` re-runs). UPDATE and DELETE on `audit_log` raise |
| `psql ... -c "TRUNCATE audit_log"` (same DB, as the app role `falcon`) | **`TRUNCATE TABLE`, count 11 → 0** (Finding 2) |
| `uv run pytest -q packages/falcon_core/tests/contracts` | `10 passed` |
| `make eval-gate` | exit 0, **SKIPPED** (no baseline). Not a pass |
| `make scan` | exit 0. gitleaks `no leaks found`; pip-audit `No known vulnerabilities found`; trivy HIGH/CRITICAL 0; syft not installed |
| `make guard` | `check_no_live_urls: ok` |
| "safe" grep on the added lines in services/packages | no matches |
| Injection probe `scratchpad/probes/pr6_inject.py` (StubLLM overrides acting as a compromised or hallucinating model; marker `http://evil-login.example.com/verify`) | see Findings 1 and 3 |

### Probe output (abridged)
```
summary.en stored: Ignore prior notes. Operators must visit http://evil-login.example.com/verify to confirm.
generated_by llm
claims: [{'text_en': 'Victims should log in at http://evil-login.example.com/verify', 'evidence_ids': ['evt_01M7...']}]
severity_reason: {'en': 'See http://evil-login.example.com/verify', ...}
rejected: [{'tool': 'upsert_incident', 'reason': 'not_allowed'}, {'tool': 'block_indicator', 'reason': 'provenance'}]
HTTP OUT: POST http://am.test:9093/api/v2/alerts [..."annotations":{"summary":"Ignore prior notes. Operators must visit http://evil-login.example.com/verify to confirm."}...]
fl:jobs entry fields: {'data': '{"kind": "requeue_check", "indicator": "9f3a61c4d27e08b2", "indicator_kind": "dom_hash", ...}'}
board summary has LIVE: True
```
The probe also confirmed these guards work: `upsert_incident` proposed by the LLM → `not_allowed`, and blocking the official fixture domain → `provenance`.

## Findings

### Blocking
1. **MEDIUM-HIGH: LLM free text isn't verified or defanged, and it reaches Alertmanager automatically.**
   - The verifier only checks that each claim cites a real id (`graph.py:326-329`, `_valid_ids` at `:141`). It never looks at the text.
   - `summary.en/ar`, each `claims[].text_en` and `severity_reason.en/ar` are stored exactly as the model wrote them (`graph.py:307-311`, `:331-337`).
   - So a live, undefanged URL that isn't in the evidence was persisted, published to `fl:board` (`sentinel.py:439-441`), and POSTed to Alertmanager as `annotations.summary` (`sentinel.py:409,419`). From there it goes to the Telegram/webhook receivers, which are external, with no operator approval.
   - This breaks CONTRACTS invariant 5 ("URLs in any output are defanged"). It also weakens "nothing can send externally": the alert channel carries model-controlled text. A small local model can easily be steered by injected indicator, registrar or correlation-key strings.
   - The "verifier drops uncited claims" requirement is met for the id check only. A claim that cites an id but asserts something unrelated passes.
   - *Fix:*
     - (a) Defang every URL or domain in LLM text before storing it (reuse the falcon_core defang helper).
     - (b) Reject the LLM summary or reason, and fall back to the template, when the text contains a URL, domain, IP, phone number or e-mail that isn't in `view.indicators`, or a number that isn't derivable from the view. Apply this per claim, and drop failing claims.
     - (c) Build `raise_alert` annotations from template fields only (type, severity, rule ids, indicator count, incident id), never from the LLM summary.
     - (d) Add tests: an injected URL in the summary is defanged or rejected; the Alertmanager body never contains LLM text; an LLM claim with a valid id but a foreign domain is dropped.
2. **MEDIUM: `audit_log` isn't append-only against TRUNCATE.**
   - The trigger is `BEFORE UPDATE OR DELETE ... FOR EACH ROW` (`db.py:41-45`). Row triggers don't fire on `TRUNCATE`.
   - Run as the service role, `TRUNCATE audit_log` emptied the table (count 11 → 0, see Checks).
   - The service role also owns the table, so it can `ALTER TABLE audit_log DISABLE TRIGGER` (it returned `ALTER TABLE`).
   - *Fix:*
     - Add `CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION fl_audit_immutable();`.
     - Extend `test_repo_roundtrip_and_audit_is_append_only` to assert that TRUNCATE raises.
     - Recommended (non-blocking if L1 agrees to defer to platform): put the table under a separate owner role, and give the sentinel role only `INSERT, SELECT` (`REVOKE UPDATE, DELETE, TRUNCATE`), so the trigger can't be disabled by the app.
3. **MEDIUM, contract: `requeue_check` writes an undeclared message to `fl:jobs`, and it can requeue a hash.**
   - `_requeue` (`sentinel.py:306-323`) XADDs `{"data": json}` to `fl:jobs`.
   - PR #4 defines `fl:jobs` entries as `verdict_id, input_type, payload_json, submitted_at, source` (its `docs/CONTRACTS.md` section). `tools.schema.json` defines no requeue message.
   - The worker (T-012) will reject the entry or DLQ it.
   - `RequeueArgs.url` accepts any indicator kind, so the probe queued `indicator_kind: dom_hash` with value `9f3a61c4d27e08b2`, which isn't checkable.
   - *Fix:* emit a contract-conformant job: a new `vd_` ULID, `input_type=url`, `payload_json={"url": <refanged>, "canonical_sha256": ...}`, and `source` (`replay` or `synthetic` per the incident). Alternatively use a separate declared stream; L1 decides, coordinating with PR #4. Restrict `requeue_check` to `url`/`domain` indicators, and add a test that asserts the exact entry fields.

### Non-blocking
4. **LOW: the STIX bundle is built and then thrown away.** `run_action` keeps only `objects` and `bundle_id` (`sentinel.py:538-540`). Nothing persists or serves the bundle, so `export_stix` exports nothing an analyst can retrieve. Persist it (or serve `GET /internal/incidents/{id}/stix`). `_pattern` maps `ip` → `ipv4-addr` even for IPv6 (`stix.py:42`); also, validating once against the `stix2` library in tests would be cheap insurance.
5. **LOW: operator identity.** Approvals are authenticated with one shared `FL_OPERATOR_KEY`, and the actor is always recorded as `"operator"` (`main.py:162-166`), so the audit trail can't tell operators apart. Take an operator name header, still authenticated by the key, or use per-operator keys.
6. **LOW: `GET /internal/incidents[/{id}]` has no auth** (`main.py:169-180`). The gateway doesn't route it, but any container on the `app`/`data`/`observability` networks can read every incident. Require the operator key, or bind it to the data network only.
7. **LOW:** `langsmith` arrives transitively with langgraph. Set `LANGSMITH_TRACING=false` (and `LANGCHAIN_TRACING_V2=false`) explicitly in the sentinel compose env, so a stray env var can never ship incident data to a third party.
8. **LOW:** `services/sentinel/src` isn't under mypy strict. Track this as a follow-up card.
9. **INFO:** the budget check `steps > MAX_STEPS` (`graph.py:189`) allows a 9th LLM step. That's harmless, but `>=` matches "8 steps".

## Eval impact
None yet. Sentinel evals (P5 / G5) aren't in this PR, and no metrics are claimed.
