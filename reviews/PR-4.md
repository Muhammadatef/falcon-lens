# PR-4 review: T-013 REST check endpoints + SSE + ?wait, T-015 make smoke

- GitHub PR #4 (new repo) · branch `feat/api-check` · head `ea60ce9` · merges cleanly into `origin/main`
- Task: T-013 / T-015 (builder-platform, P0) · **round 1 of 2** · reviewer: supervisor (L2) · 2026-11-22
- This file replaces the old repo's PR-4 review (T-003 SSRF guard). That text is still in git at `6d0251e:reviews/PR-4.md`.
- Worktree: `/tmp/fl-review-api-check`, set up with `uv sync --all-packages`

## Verdict: **APPROVE**, with one merge condition for L1

Every T-013 acceptance item is covered by tests or by my probes. No blocking defects.

**Merge condition (L1, not the builder):** the PR adds a new `docs/CONTRACTS.md` section, "Internal messages (API <-> worker)", and a generated `contracts/openapi.yaml`. Contracts are L1's (CLAUDE.md, HIERARCHY), and the card says "L1 reviews diff". L1 has to ratify both explicitly when merging. Note that PR #6 (sentinel) currently writes a *different* message shape to the same `fl:jobs` stream (see Finding 1).

The smoke script can't run against a real worker yet because T-012 hasn't landed. As instructed, I did not block on this. The fake-worker mode labels itself "NOT a G1 result" (`scripts/smoke.sh:34`, `scripts/smoke.py:215`), and the fake worker is behind compose profile `smoke-fake`, so `make up` never starts it.

## Checks run

| Command | Result |
|---|---|
| `uv sync --all-packages && make test` | exit 0. ruff `All checks passed!`, format `82 files already formatted`, mypy `Success: no issues found in 35 source files` (now includes `services/api/src`), pytest `340 passed, 1 skipped, 1 warning in 16.74s` |
| `uv run pytest -q packages/falcon_core/tests/contracts` | `10 passed` |
| `uv run python scripts/gen_openapi.py --check` | exit 0 (committed openapi.yaml matches the code) |
| `uv run python scripts/check_openapi_drift.py` | `openapi-drift: ok` |
| `make eval-gate` | exit 0, **SKIPPED** (no baseline). Not a pass |
| `make scan` | exit 0. gitleaks `no leaks found`; pip-audit `No known vulnerabilities found`; trivy HIGH/CRITICAL 0; syft not installed |
| `make guard` | `check_no_live_urls: ok` |
| URL grep on the diff | only fixture, `.test` and `example` hosts, plus `169.254.169.254` as the smoke SSRF *input*. That address is meant to be rejected, and is not a fetch target |
| Probe `scratchpad/probes/pr4_api.py` (in-process ASGI, fakeredis) | see below |

### Probe results
- **No input echo.** I put a marker string in the URL body (as int, list, control chars), in the message, in a 413 message, in a .txt-as-eml, in non-image bytes, in malformed JSON, and in `?wait=`. All returned problem+json with **no marker** in the body. Validation errors give only `loc` + `type` (`problem.py:76-78`).
- **Path echo.** `instance` echoes the request path: `GET /v1/verdicts/<script>x` → `"instance":"/v1/verdicts/<script>x"` (`problem.py:52`). The response is JSON with `nosniff` at the gateway, so it isn't executable. See Finding 3.
- **?wait.** `?wait=100` returned 202 in 8.0 s, so the cap holds. `?wait=-1` → 422.
- **Source spoofing.** Anonymous `X-Falcon-Source: fixture` → job `source=live`. With a key → `fixture` (`app.py:251-253`).
- **Screenshot.** Anonymous callers get `screenshot_url` null on GET, SSE and cached paths. A bearer key or `X-API-Key` gets it (`jobs.py:42-47`, `test_checks.py:171-182`).
- **Rate limit.** A public peer (`8.8.8.8`) gets `[202,202,202,429,429,429]` at limit 3, and rotating `X-Forwarded-For` doesn't help. A private peer has its XFF last hop trusted by design (`app.py:83-95`).
- **Trailing slash.** `POST /v1/check/url/` → 307 with no enqueue.

## Findings (all non-blocking)

1. **MEDIUM, cross-PR contract: `fl:jobs` shape conflict with PR #6.**
   - This PR defines `fl:jobs` entries as `verdict_id, input_type, payload_json, submitted_at, source` (`docs/CONTRACTS.md` new section).
   - PR #6's `requeue_check` writes `{"data": "{kind: requeue_check, ...}"}` to the same stream (`falcon_core/tools/sentinel.py:308-322`).
   - L1 must choose one contract before T-012 consumes the stream. I raised it as blocking on PR #6, not here.
2. **MEDIUM, availability: SSE and GET aren't rate-limited.**
   - The limiter only covers `POST /v1/check/*` (`app.py:177-187`).
   - An anonymous client can open unlimited `GET /v1/verdicts/{id}/events` streams on one known id. Each stream holds a Redis pub/sub connection for up to 120 s (`SSE_MAX_S`, `app.py:45`).
   - THREAT_MODEL row D lists per-IP limits. Follow-up: add a per-IP cap on concurrent SSE streams (for example, a Redis counter with a TTL) and a light GET limit.
3. **LOW: `instance` reflects the raw path** (`problem.py:52`). Use the route template (for example `/v1/verdicts/{verdict_id}`) or drop `instance` on 404/422. That keeps the "never echo input" rule literal.
4. **LOW: per-key limits aren't implemented.** The card says "rate limit per IP/key", and THREAT_MODEL says "per-IP and per-key". Keyed callers currently share the per-IP bucket. Add a `rl:key:<sha>` bucket when there's more than one key.
5. **LOW, deployment (carry to platform/gateway): XFF trust.** `client_ip` trusts the last XFF hop from any private peer (`app.py:87`). Caddy without `trusted_proxies` replaces XFF with its peer address. Behind the Cloudflare tunnel, that means every public demo user shares one bucket of 60/min. Configure Caddy `trusted_proxies` and `client_ip_headers Cf-Connecting-IP` for the tunnel path. Also, Python's `is_private` includes TEST-NET ranges, which is harmless here but worth knowing.
6. **LOW: idempotency.** A response returned via `?wait` (200 or a 202 partial) is not stored under the Idempotency-Key (`app.py:294-298`; only the bare-accepted path calls `idem_save`). A retry re-enters single-flight or cache, so it's still correct. Store the `Accepted` body in every branch so replays are byte-stable.
7. **LOW: cached path.** In `submit`, `j.latest(...)` (`app.py:282`) isn't wrapped for `RedisError`, so a Redis blip there gives a generic 500 instead of the 503 `queue-unavailable`.
8. **INFO, missing tests:** no unit test for the `client_ip` XFF trust rule, and none for authenticated SSE getting `screenshot_url`. Add both with the follow-ups above.

## Eval impact
None. No metrics are claimed. `fl_rate_limited_total{scope}` and `fl_api_jobs_enqueued_total{input_type}` are new and need to go into OBSERVABILITY / T-014.
