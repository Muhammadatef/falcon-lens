# PR-6 review: T-001 platform skeleton (uv workspace, services, compose, Makefile, CI)

- Former GitHub PR #6. The repo is being recreated, so I reviewed the local branch `keep/feat/platform-skeleton`, head `cd39eb6`, merge-base with main `8a6de20`.
- Task: T-001 (builder-platform, P0). Round 1 of 2. Reviewer: supervisor (L2). Date: 2026-11-22.
- Worktree: `/tmp/fl-review-6`, with `.env` copied from `.env.example`. I did not read the owner's `.env`.

## Verdict: **CHANGES REQUESTED**. G0 is **NOT confirmed** on this branch.

The stack itself is solid:
- All 17 core and obs containers came up healthy.
- Services run as non-root, with read-only rootfs, `cap_drop: ALL` and `no-new-privileges`.
- Tests, contract tests and scan are green.
- I found no secrets and no live URLs.

Five problems block the merge. The most serious is that the sandbox is dual-homed onto the `observability` network. From inside the sandbox I reached 14 internal endpoints, including the API, Alertmanager, Prometheus, Loki and Alloy. That defeats the isolation the threat model relies on.

G0 is not confirmed for three reasons:
- The branch is not approvable.
- My run used project `falcon` and a worktree, not a fresh clone with `COMPOSE_PROJECT_NAME=falcon-review`. The coordinator's isolation rule arrived after my stack was already up.
- The permission system denied tearing down that stack so I could re-run it under `falcon-review` (see "Open items for L1").

So `reviews/GATE-G0.md` is not written.

## Checks run

| # | Command | Result |
|---|---|---|
| 1 | `make test` (ruff check, ruff format --check, mypy strict, pytest) | exit 0. `All checks passed!`, `27 files already formatted`, `Success: no issues found in 12 source files`, `15 passed, 1 warning in 0.88s` |
| 2 | `uv run pytest packages/falcon_core/tests/contracts -q` | exit 0, `10 passed in 0.08s` (there is no top-level `tests/contracts`) |
| 3 | `make eval-gate` | `No rule to make target 'eval-gate'` (not built yet; see finding 4) |
| 4 | `make smoke` / `make eval` | both exit 2 with `make smoke: not yet implemented` / `make eval: not yet implemented`. This meets T-001 acceptance |
| 5 | `make scan` | exit 0. gitleaks: `20 commits scanned … no leaks found`. pip-audit: `No known vulnerabilities found`. pnpm audit: clean. trivy fs (vuln, secret, misconfig; HIGH and CRITICAL): 0 on `uv.lock`, `web/pnpm-lock.yaml` and all 9 Dockerfiles. `WARN: syft not installed; SBOM skipped` |
| 6 | `gitleaks dir . --no-banner` | `no leaks found` |
| 7 | `make up` (project `falcon`) | exit 0 in 1m33s, `All services healthy.` |
| 8 | `docker compose --profile core --profile obs ps` | **17/17 `(healthy)`**: alertmanager, alloy, api, egress-proxy, gateway, grafana, loki, mcp, otel-collector, phoenix, postgres, prometheus, redis, sandbox, sentinel, web, worker. Host ports are bound to loopback only (127.0.0.1:8443, 3001, 9090) |
| 9 | `curl -sk https://localhost:8443/` | `200` |
| 10 | `curl -sk https://localhost:8443/v1/version` | `HTTP/2 200`, `{"service":"falcon-api","api":"v1","env":"local"}`. Headers present: CSP, HSTS, nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, Permissions-Policy, COOP. `Server` is stripped |
| 11 | `docker network inspect` (all 6 nets) | `sandbox` (internal): sandbox and egress-proxy only. `sandbox_ctl` (internal): sandbox and worker. **`observability` (internal): 14 members, including sandbox**. `app` and `edge` are not internal |
| 12 | TCP probe from `falcon-sandbox-1` (`scratchpad/probe.py`) | OPEN to api:8000, mcp:8000, sentinel:8000, worker:8000, gateway:8443, gateway:8080, grafana:3000, prometheus:9090, alloy:12345, loki:3100, otel-collector:4317, phoenix:6006, alertmanager:9093. postgres, redis and web: no DNS. `1.1.1.1:443`: OSError (no direct internet, as intended) |
| 13 | HTTP from the sandbox with the env proxy bypassed (`ProxyHandler({})`, `scratchpad/probe3.py`) | `200` from: alertmanager `/api/v2/status`, prometheus `/api/v1/status/config` (returns the full scrape config), api `/v1/version`, loki `/ready`, grafana `/api/health`, alloy `/-/ready`, phoenix `/healthz`, worker `/metrics` |
| 14 | CONNECT through egress-proxy from the sandbox | `403` for `api:8000`, `gateway:443`, `169.254.169.254:80` and `localhost:443`. A plain `GET http://…` gets `405` (the proxy only accepts CONNECT) |
| 15 | `docker exec … id` and `docker inspect` | api, worker, mcp, sentinel and egress run as uid 10001. sandbox runs as `pwuser` (1001), web as `node` (1000), gateway as 65532, otel and loki as 10001. Rootfs is read-only with caps `[ALL]` dropped and `no-new-privileges` on all core services except loki (`ReadonlyRootfs=false`) |
| 16 | grep the diff for `https?://`, `hxxp`, `www.` (lockfiles excluded) | only tooling URLs (the gitleaks release, pre-commit repos) and the fixture `hxxps://falcon-demo-bank[.]test/login`. No live phishing URLs and no logos |
| 17 | grep the diff for `\bsafe\b` and `dangerouslySetInnerHTML` | only "DNS-rebinding-safe" in a code comment (`services/egress/src/falcon_egress/guard.py:4`). No `dangerouslySetInnerHTML` |
| 18 | Integration overlay: the skeleton plus the `packages/**` files from `keep/feat/security-ssrf-egress` (#4), `keep/feat/signals-url` (#5) and `keep/feat/core-arbiter` (#7), in scratch worktree `/tmp/fl-review-6-int` (since removed) | See finding 3. pytest: `ModuleNotFoundError: No module named 'tldextract'`. After adding the deps: `16 failed` with `KeyError: 'display'`, because the branch has no `data/`. After overlaying main's `data/ config/ contracts/`: **`1138 passed, 1 skipped`**. ruff: **`Found 179 errors`** (164 E501). ruff format: `25 files would be reformatted`. mypy: **`Duplicate module named "conftest"`** |
| 19 | `uv build --package falcon-core` (overlay) | the wheel already contains `py.typed`, `i18n/ar.yaml`, `i18n/en.yaml`, `scoring/params.yaml` and `signals/url/data/confusables.txt` plus its licence. Hatchling includes package data by default |

## Findings

### Blocking

**1. P0: the sandbox is on the `observability` network.** Locations:
- `docker-compose.yml:149`: `networks: [sandbox, sandbox_ctl, observability]`
- `infra/prometheus/prometheus.yml:30`: scrape target `sandbox:8000`
- DECISIONS line "The sandbox also joins the internal `observability` network…"

The problem:
- ARCHITECTURE §Sandbox says the sandbox's "only network is `sandbox`, whose only peer is `egress-proxy`". THREAT_MODEL rows I and E rely on that.
- Checks 12 and 13 show that code running in the sandbox container can reach the API directly, bypassing the gateway and its limits. It can also reach MCP, Sentinel, the worker and the gateway listeners.
- Worst of all, it reaches unauthenticated Alertmanager (`POST /api/v2/alerts` means forged alerts, and later Telegram), Loki push (forged logs on the dashboards), Phoenix (forged traces), Prometheus (a recon dump of the whole topology) and Alloy, which holds `docker.sock`.
- `HTTP_PROXY` is only advisory. A renderer escape, or any code path that ignores the env var, goes straight past it.

Fix:
- Remove `observability` from the sandbox, and remove the `sandbox:8000` Prometheus job.
- Logs: Alloy already tails container logs through `docker.sock`, so no network is needed.
- Metrics: the worker relays them. Either it fetches `sandbox:8000/metrics` over `sandbox_ctl` and re-exposes them, or the sandbox returns timings in each visit response and the worker records the `fl_sandbox_*` metrics.
- Traces: the worker opens the spans around sandbox calls.
- Acceptance: the sandbox probe (check 12) shows only `egress-proxy:3128` and `worker:8000` open.

**Judgement on `sandbox_ctl`: accepted**, with these conditions:
- (a) L1 records it in ARCHITECTURE §Sandbox. The doc currently says "only network is `sandbox`".
- (b) The worker listens on `sandbox_ctl` only for `/healthz` and `/metrics`. It never exposes a job or control API there, because Docker networks are not directional and the sandbox can reach `worker:8000`.
- (c) The sandbox API authenticates the worker with a shared token from env, so a stray peer can't drive visits.

Putting the worker on `sandbox` instead would be worse: it would sit on the same L2 segment as attacker-driven traffic.

**2. P0: the branch is 7 commits behind main and must be rebased.**
- Merge-base `8a6de20`. Main has since changed `contracts/event.schema.json` (`previous_verdict`, `script_fingerprint`) and added `data/brands.yaml` (348 lines).
- The branch has no `data/` directory at all, which is why the #5 tests fail with `KeyError: 'display'` (check 18).
- In the overlay, the skeleton's round-trip tests passed against main's contracts. That is encouraging, but it has to be proven on the rebased branch.
- `DECISIONS.md` will conflict and needs a manual merge.

**3. P0: integration prerequisites for #4, #5 and #7.**
- Ownership: the root `pyproject.toml`, `packages/falcon_core/pyproject.toml`, the Dockerfiles and compose belong to builder-platform. The feature PRs add code under `packages/falcon_core` without touching them.
- Measured result: after merge, `make test` fails on all three PRs (check 18).
- Fix: the skeleton must add the items below. Each was measured in the overlay.

| # | Item | Why (evidence) |
|---|---|---|
| a | `falcon-core` runtime deps: `httpx>=0.28`, `httpcore>=1` (imported directly in #4 `security/http.py`), `tldextract>=5` (#5 `signals/url/canonical.py:11`), `pyyaml>=6` (#5 `signals/brands/registry.py`, #7 `scoring/params.py` and `i18n`) | `ModuleNotFoundError: No module named 'tldextract'`. `httpx` is currently only a dev dep at `pyproject.toml:42`, but #4 uses it at runtime as `ctx.http` |
| b | dev: `types-PyYAML`. Keep `pytest-asyncio`, `jsonschema`, `types-jsonschema` and `referencing` (#7 imports `referencing.jsonschema`) | With these added, `mypy packages/falcon_core/src` gives `Success: no issues found in 34 source files` |
| c | Lint config: pick one line length. At `line-length = 100`: `179 errors` (164 E501; the longest lines are 139 in signals, 120 in scoring and 114 in i18n). At 120: `13 errors`, 11 auto-fixable. **Recommendation: L1 decides. Either 120 in the skeleton, or keep 100 and have #5/#7 run `ruff format` plus manual wraps on rebase.** Also add `"**/tests/**" = [..., "S311"]` (seeded `random` in `tests/scoring/test_properties.py:73,106`) and `[tool.ruff.lint.isort] known-local-folder = ["conftest", "scoring_helpers"]` (I001 on `from conftest import …`) | measured |
| d | mypy: `tests/signals/conftest.py` and `tests/scoring/conftest.py` collide (`Duplicate module named "conftest"`). Fix: set `explicit_package_bases = true` and `mypy_path = "packages/falcon_core/tests"`, or move the shared helpers into one importable `tests/_helpers` package. Then decide test strictness: excluding the conftests leaves `48 errors in 4 files` (31 in `test_url_signals.py`, 12 in `test_canonical.py`, 2 in `test_i18n.py`, 1 in `signals/conftest.py`; mostly `no-untyped-def`). Either add a `[[tool.mypy.overrides]]` for tests with `disallow_untyped_defs = false`, or have #5 annotate. CLAUDE.md requires strict only for `packages/falcon_core` itself | measured |
| e | Package data: already handled. Hatchling ships `py.typed`, the yaml files and `confusables.txt` (check 19). Add a test that asserts these files are in the built wheel, so a future `[tool.hatch]` include list can't silently drop them | check 19 |
| f | Repo data inside images: `.dockerignore` excludes `data` wholesale. #5 `registry.py:_find_yaml` walks parent dirs for `data/brands.yaml`, and #7 `reasons.py:_default_channels_path` walks them for `config/reporting_channels.yaml`. Neither file exists in `/opt/venv` images, so `default_registry()` raises `FileNotFoundError`. Fix: add `!data/brands.yaml` to `.dockerignore`; `COPY data/brands.yaml config/ /app/…` in the worker, api and sentinel images; set `FALCON_BRANDS_YAML` and `FL_REPORTING_CHANNELS` in `x-app-env` | code read |
| g | `tldextract` must stay offline in read-only containers. #5 already sets `suffix_list_urls=(), cache_dir=None` (`canonical.py:40`), which is correct. Keep it that way, and add no `TLDEXTRACT_CACHE` | code read |
| h | `pytest` config `testpaths` must include `packages/falcon_core/tests` (it does). Keep `asyncio_mode = "auto"`, which #4's async tests rely on | `pyproject.toml:74-76` |

**4. P1 (blocking under the CLAUDE.md "never pass silently" rule): the CI `eval-gate` job is a green no-op.** `.github/workflows/ci.yml:79-84` only runs `echo "TODO …"`, so every PR shows a passing eval gate that gates nothing. Fix: make it `exit 1` with "not yet implemented" and keep it out of required checks until builder-evals lands it, or delete the job.

**5. P1: host ports are hard-coded.** See `docker-compose.yml:84` (`127.0.0.1:8443:8443`), `:274` (`9090`) and `:372` (`3001`). Builders now run stacks in parallel under separate `COMPOSE_PROJECT_NAME`s, and a second stack can't start with these fixed host ports. Fix:
- Use `127.0.0.1:${FL_GATEWAY_PORT:-8443}:8443`, `${FL_PROMETHEUS_PORT:-9090}` and `${FL_GRAFANA_PORT:-3001}`.
- Add them to `.env.example` and use them in the `make up` banner (Makefile:17-19).
- Let `scripts/wait_healthy.sh` honour `COMPOSE_PROJECT_NAME`. It already does, implicitly, through `docker compose`.
- `name: falcon` at `docker-compose.yml:1` is fine, because the env var overrides it.

### Non-blocking (track them; fix by the noted milestone)

**6. P1: CSP `script-src 'unsafe-inline'`** (`infra/gateway/Caddyfile:29`).
- **Acceptable for G0.** The web app renders no untrusted content yet: `web/app/*` is static, and the form makes no backend call.
- **It must be gone before the incident board or any verdict text renders (G1 public demo).** THREAT_MODEL row E requires "no inline scripts, nonce-based".

Nonce plan:
- (a) Add a Next.js 16 `proxy.ts` (formerly `middleware.ts`) that generates a per-request nonce (`crypto.randomUUID()` base64).
- (b) That file sets `Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-<n>' 'strict-dynamic'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'` on both the request and the response. Next applies the nonce to its own hydration scripts automatically.
- (c) Pages that need the nonce render dynamically.
- (d) Caddy keeps its CSP only on `/v1/*` and `/mcp*` (or adds a strict `default-src 'none'` there) and stops setting it on the web route, so two policies don't stack.
- (e) Add a Playwright test that asserts no CSP violations and that the XSS payload fixtures don't execute.

`style-src 'unsafe-inline'` may stay; it's lower risk and React style attributes need it.

**7. P1: app services have direct internet access.** `app` is not internal (DECISIONS, documented), so api, worker, sentinel and mcp can reach the internet without the egress proxy. ARCHITECTURE shows "egress via proxy". This is handed off to builder-security, and #4's `ctx.http` must enforce the proxy. Tracked, not blocking G0.

**8. P2: images are pinned by tag, not by digest.** `nginxinc/nginx-unprivileged:1.29-alpine`, `alpine:3.22` and `node:24.15-alpine` are minor-pinned only. GitHub Actions use `@v4`/`@v6` tags, not SHAs. Pin by `@sha256:` digest and action SHAs before the freeze (Tue 22:00).

**9. P2: `make scan` gaps against THREAT_MODEL.** It has no `docker inspect` checks for the sandbox (read-only, `cap_drop`, `no-new-privileges`, network membership; the check from finding 1 belongs here), no semgrep, and syft is not installed locally, so no SBOM was produced.

**10. P2: egress stub limits.** It is CONNECT-only (`services/egress/src/falcon_egress/main.py:64`), so Chromium's plain `http://` proxy requests get `405`. The guard (`guard.py`) is fail-closed with `is_global`, which also blocks Docker-internal service IPs (check 14: `api:8000` gives 403). That is fine as a placeholder until #4 plugs the real guard in. builder-sandbox needs to know about the plain-HTTP gap.

**11. P2: the contract models in this PR overlap T-002.** `packages/falcon_core/src/falcon_core/contracts/*.py` don't enforce invariants 2–4 (`safe`, `caution`, degraded). `verdict.py:63,94` has no validators. Those invariants are T-002 acceptance criteria, and T-002 belongs to agent-core. L1 should confirm whether T-002 takes these files over.

**12. P2: hardening exceptions, all documented in DECISIONS and accepted for a local stack.** Postgres has no `cap_drop`. Loki has no `read_only`. Alloy runs as root with `docker.sock` read-only. Alloy stops being reachable from the sandbox once finding 1 is fixed.

**13. P2: fixture form.** `services/fixtures/html/index.html:11` has `action="#" method="post"`. It is neutralised by `onsubmit="return false"` and a disabled button. Dropping `action` and `method` entirely would meet the "posts nowhere" rule literally.

## Eval impact
None. No scoring or signal code is touched. No metrics appear in any doc in this diff.

## G0
- **What passed:** health and gateway behaviour (checks 7–10) on this branch, under project `falcon`.
- **What is not confirmed:**
  - (a) Findings 1–5 are open.
  - (b) G0 needs a run on a fresh clone of the merged main, with `COMPOSE_PROJECT_NAME=falcon-review` and the T-001 network acceptance, after the finding 1 fix: the sandbox can reach only egress-proxy and the worker.
  - (c) My re-run under `falcon-review` was blocked (below).

I'll write `reviews/GATE-G0.md` after round 2.

## Open items for L1
- **A stack is still running.** Project `falcon`, 17 containers, `working_dir=/tmp/fl-review-6`, started by me before the isolation rule arrived. It holds host ports 8443, 3001 and 9090. The permission system denied my `docker compose -p falcon -f /tmp/fl-review-6/docker-compose.yml … down`. Run it yourself (L1/owner) or grant permission.
- **Worktree kept.** `/tmp/fl-review-6` is still in place because that stack bind-mounts its config files (Caddyfile, prometheus, loki, otel, grafana and alloy configs). Remove it with `git worktree remove /tmp/fl-review-6` after the stack is down. The scratch integration worktree `/tmp/fl-review-6-int` has already been removed.
