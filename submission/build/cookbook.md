# Falcon Lens Cookbook

**A hands-on guide for a technical teammate.** It takes you from a fresh clone to a running stack, then walks through the everyday recipes: checking a link, calling the API, connecting an MCP client, loading the Chrome extension, reading dashboards, approving a Sentinel action, adding a brand or a fixture, running the local model, and sending a pull request.

Every command here exists in the repository (`Makefile`, `scripts/`, `docs/`). The build script `submission/build/verify_cookbook.py` checks each `make` target and each file path in this guide against the checkout, so the guide cannot drift. Numbers about quality are not in this guide on purpose: they live in `evals/results/published/`.

> Falcon Lens is an independent project. It is not affiliated with or endorsed by Abu Dhabi Police, and it is ready to connect, not connected, to any police system.

## 1. Prerequisites

| You need | Why | Check |
|---|---|---|
| Git and `make` | clone and run targets | `git --version`, `make --version` |
| Docker with Compose v2 | the whole stack runs in containers | `docker compose version` |
| `uv` | Python 3.12 workspace and scripts | `uv --version` |
| `Node 24` and `pnpm` | web app tests and the Chrome extension build | `node --version`, `pnpm --version` |
| `gh` (GitHub CLI) | open and inspect pull requests | `gh auth status` |
| Ollama (optional) | local models and sovereign mode | `ollama --version` |
| `cloudflared` (optional) | public tunnel for a phone demo | `cloudflared --version` |
| Chrome | to load the extension | |

Give Docker a few CPUs and several gigabytes of memory; the stack runs a browser pool, Postgres, Redis and the observability services.

## 2. Get it running

### 2.1 Clone and configure

```bash
git clone https://github.com/Muhammadatef/falcon-lens
cd falcon-lens
cp .env.example .env
```

`.env` is gitignored. **Never commit it and never paste its contents anywhere public.** Every key is optional: an empty key switches the related feature off and the dashboards show it as disabled. The sections of `.env.example`, explained:

| Key (group) | What it does | Where to get it | Needed? |
|---|---|---|---|
| `FL_ENV` | `local`, `demo` or `ci`. Outside `local` the API refuses to start while secrets still read `change-me` | choose | Yes, keep `local` |
| `FL_SOVEREIGN_MODE` | `true` sends every model call to the local model; no content leaves the machine | choose | Optional |
| `FL_PUBLIC_BASE_URL` | Public origin the app allows (set to the tunnel URL for a phone demo) | `make tunnel` | Optional |
| `FL_GATEWAY_PORT`, `FL_PROMETHEUS_PORT`, `FL_GRAFANA_PORT` | Host ports, bound to 127.0.0.1 only | choose | Change only on a clash |
| `ANTHROPIC_API_KEY` | Cloud model for the Investigator and Sentinel. Empty means local-only mode, same as sovereign | an Anthropic Console account | Optional |
| `FL_CLOUD_MODEL_*`, `FL_LLM_TIMEOUT_S`, `FL_SHADOW_RATE` | Which cloud model per role, timeout, share of calls also sent to the other route to measure agreement | keep defaults | No |
| `OLLAMA_BASE_URL`, `FL_LOCAL_MODEL`, `FL_LOCAL_VISION_MODEL`, `FL_LOCAL_WORKER_MODEL`, `FL_EMBED_MODEL`, `FL_EMBED_DIM`, `FL_LOCAL_LLM_TIMEOUT_S` | Local model runtime and model names | Ollama on this machine or another one (section 4.10) | Optional |
| The two reputation keys under "Reputation feeds" | Google browsing-protection and URLhaus feeds. Empty means disabled | Google Cloud Console (its web-protection lookup API) and an abuse.ch account (URLhaus Auth-Key) | Optional |
| `FL_FEED_OPENPHISH_ENABLED` | The OpenPhish community feed mirror. It allows research use only, so respect its terms | none | Default on |
| `POSTGRES_*`, `DATABASE_URL`, `REDIS_URL` | Data stores inside the stack | defaults are fine locally | No |
| `FL_API_KEY_PEPPER` | Secret mixed into API key hashes | any long random string | Change outside local |
| `FL_SANDBOX_API_KEY` | Public key with the `check` scope only and a low rate limit | defaults | No |
| `FL_OPERATOR_KEY` | Approves or rejects held Sentinel actions (scopes `read`, `operator`) | any long random string | Change outside local |
| `FL_MCP_BEARER_TOKEN`, `FL_MCP_SERVICE_KEY` | Bearer token MCP clients send; key the MCP server uses against REST (`check`, `read` only) | any long random strings | Change outside local |
| `FL_WEBHOOK_SECRET`, `FL_WEBHOOK_TARGETS` | HMAC secret and comma-separated https targets for signed campaign alerts | your receiver | Optional |
| `FL_SANDBOX_TOKEN`, `FL_SANDBOX_URL` | Worker-to-sandbox shared secret and address (internal network) | any long random string | No |
| `FL_SSRF_ALLOW_HOSTS`, `FL_SMOKE_*` | Invented fixture hosts the guard lets through, only when `FL_ENV` is local, demo or ci | defaults | No |
| `FL_RATE_LIMIT_PER_IP_PER_MIN` | Anonymous per-IP limit | choose | No |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ALERT_WEBHOOK_URL` | Where Alertmanager sends alerts; empty keeps alerts in Grafana and logs | BotFather on Telegram, or your webhook | Optional |
| `GRAFANA_ADMIN_PASSWORD` | Grafana admin login | choose | Yes, set one |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Telemetry collector | default | No |

The repository check `make guard` runs `scripts/check_env_example.py`, so `.env.example` stays complete.

### 2.2 Start, seed, smoke-test

```bash
make up        # core + observability; waits until every service is healthy; prints the URLs
make seed      # push the demo corpus through the real API and worker, labelled source=replay
make smoke     # end-to-end assertions against the running stack
make urls      # print the addresses again at any time
```

`make up` fails with a clear message if `.env` is missing. The app is at `https://localhost:8443` with a local certificate authority, so accept the browser warning once (use `curl -k` on the command line). Grafana is at `http://localhost:3001` (user `admin`, password from `GRAFANA_ADMIN_PASSWORD`), Prometheus at `http://localhost:9090`. To stop: `make down` (data volumes are kept).

`make smoke` starts the stack if needed. `FL_SMOKE_FAKE_WORKER=1 make smoke` uses a test double and is **not** a real pass.

### 2.3 The demo, the replay and the reset

```bash
make demo                     # core + obs + fixtures; pre-warm, seed, print URLs, run the six scenarios and the Sentinel scene
make replay RATE=2/s DURATION=10m   # steady, labelled synthetic traffic plus a planted campaign for the Sentinel
make demo-reset               # asks first, then wipes Postgres and Redis volumes and runs make demo (YES=1 skips the question)
```

`make demo` exits non-zero if any scenario fails. Everything it seeds is labelled as replayed or synthetic, and the scenarios use only the invented brand **Falcon Demo Bank**. The written scenarios and the video shot list are in `docs/DEMO.md`.

### 2.4 The quality commands

```bash
make eval        # offline eval (val + test): JSON, HTML and latest.prom under evals/results/ (needs private data)
make redteam     # prompt-injection and obfuscation suite; exits non-zero if any attack succeeds
make ci-local    # run every ci.yml job locally in parallel; logs in work/ci-local/<sha>/
make test        # ruff, ruff format check, mypy (strict on falcon_core), pytest
make guard       # defensive-only guard: no live URLs, nothing from data/private in git
make scan        # gitleaks, pip-audit, pnpm audit, trivy, semgrep, hardening checks, SBOM
make submission  # build the submission package and trace every number
```

Notes: `make eval` needs the private datasets under `data/private/`, which are not in the repository. `JOBS="lint test" make ci-local` runs a subset. `make ci-local-pr PR=123` tests the merge result of a PR and comments on it. A published eval artifact is what every document quotes: numbers are never typed.

## 3. Mental model in one page

A check enters at the gateway, becomes a job on a Redis stream, and the worker runs the cascade **T0** (cache, official registry, feed mirror), **T1** (address signals and a classifier), **T2** (the sealed browser and the brand check) and **T3** (the AI Investigator, only when unsure). The deterministic arbiter, never a model, sets the score and the verdict. A `verdict.created` event feeds the **Sentinel**, which links checks into incidents and campaigns, acts inside the system, and holds external drafts for a human. Details: `docs/ARCHITECTURE.md`, `docs/SCORING.md`, `docs/adr/`.

## 4. Recipes

### 4.1 Check a link or a message in the web app

1. Open `https://localhost:8443`.
2. Paste an address and press the check button. The verdict updates as each layer finishes.
3. For a harmless local test use the invented fixtures (only with the `tools` profile, which `make demo` starts): the lookalike `hxxp://falcon-demo-bank-secure[.]test/login` and the official site `hxxp://falcon-demo-bank[.]test/`. Un-defang them (`http://`, `.`) when you type them.

The answer carries one of three verdicts, reasons that cite evidence, and what to do now. It never certifies a link as harmless.

### 4.2 Call the API with curl

Create a key (printed once, stored only as an argon2id hash):

```bash
docker compose exec api python /app/scripts/create_api_key.py --label my-test --scopes check,read --rate-limit 120
```

Scopes: `check`, `read`, `intel`, `operator`. Then:

```bash
B=https://localhost:8443
K=<the key you just printed>

curl -sk -X POST "$B/v1/check/url?wait=8" -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: cookbook-1' -d '{"url":"http://falcon-demo-bank.test/login"}'

curl -sk -X POST "$B/v1/check/message" -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -d '{"text":"message text here"}'

curl -sk -H "X-API-Key: $K" "$B/v1/verdicts/<verdict_id>"          # poll
curl -skN -H "X-API-Key: $K" "$B/v1/verdicts/<verdict_id>/events"   # stream (SSE)
curl -sk "$B/v1/meta"                                               # shows sovereign_mode and version info
```

`?wait=8` blocks up to eight seconds and returns the best verdict so far. Errors are `application/problem+json`. A wrong key gets `401`, never silent anonymous access. More examples: `docs/api/curl-examples.md`; Postman collection `docs/api/falcon-lens.postman_collection.json`; Python client `clients/python/falcon_lens_client.py`; contract `contracts/openapi.yaml` (regenerate with `make openapi`, CI fails on drift).

### 4.3 Connect an MCP client

The MCP server speaks streamable HTTP at `https://localhost:8443/mcp`. The repository ships `.mcp.json`, which expands `FL_MCP_BEARER_TOKEN` from your environment:

```bash
set -a; source .env; set +a
claude mcp list          # shows falcon-lens when the file is picked up
curl -sk -X POST "https://localhost:8443/mcp" -H "Authorization: Bearer $FL_MCP_BEARER_TOKEN" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Tools: `check_url`, `check_message`, `check_email`, `get_verdict`, `list_campaigns`, `list_incidents`, `get_incident`, `submit_report`. MCP uses a key limited to `check` and `read`, so it can never approve an action or export intelligence. Tool output is data, not instructions. A client that insists on a trusted certificate needs the tunnel address (section 5).

### 4.4 Load the Chrome extension

```bash
pnpm --dir extension install
pnpm --dir extension build          # writes extension/dist
```

In Chrome open `chrome://extensions`, switch on Developer mode, press **Load unpacked** and choose `extension/dist`. Open the extension options to set the API base URL (default your local gateway) and an optional key. It sends only the address, warns before you type on a risky page, and offers a hover check in webmail and chat web apps. Permissions and privacy: `extension/PRIVACY.md`.

### 4.5 View the Grafana dashboards

Open `http://localhost:3001` and sign in as `admin`. Six dashboards are provisioned: overview, detection quality, pipeline performance, AI operations, security and Sentinel (files in `infra/grafana/dashboards/`, regenerated by `infra/grafana/gen_dashboards.py`). Metrics start with `fl_`. Every log line and trace span carries the `verdict_id`, so paste one into Grafana Explore (Loki) to follow a check across services. Replayed and synthetic traffic is labelled; to eyeball dashboards with clearly synthetic data run `uv run python scripts/emit_demo_metrics.py --port 9199`. Alerts each have an entry in `docs/RUNBOOK.md`.

### 4.6 Approve a Sentinel action

1. Make sure an incident exists: `make replay RATE=2/s DURATION=10m` plants a campaign.
2. Open `https://localhost:8443/ops`, paste the operator key (`FL_OPERATOR_KEY` from `.env`; it stays in the browser session only) and press Connect.
3. Open an incident, read the evidence and the draft, then approve or reject.

The same through the API (the operator key has `read` and `operator`):

```bash
O=<FL_OPERATOR_KEY>
curl -sk -H "X-API-Key: $O" "$B/v1/incidents?status=open&limit=10"
curl -sk -X POST -H "Authorization: Bearer $O" "$B/v1/incidents/<incident_id>/actions/<action_id>/approve"
```

Nothing is ever sent outside the system by the Sentinel itself: an approval records the decision, and the draft is for a person to use. To revert an automatic internal block: `make unblock ID=<action_id>` (needs `DATABASE_URL` and `REDIS_URL` reachable from your machine).

### 4.7 Read a trace and an incident

A verdict carries its own `trace` (the steps of the cascade and the evidence ids):

```bash
curl -sk -H "X-API-Key: $K" "$B/v1/verdicts/<verdict_id>"
```

The result page shows the same as a timeline with a "Technical details" switch. An incident (`GET /v1/incidents/<incident_id>`) lists indicators, evidence and actions; every action is also in the append-only audit log. Logs for the Sentinel are in Grafana Loki. {{INCIDENT_TRACE}}

### 4.8 Add a brand to `data/brands.yaml`

The brand registry tells the address signals which domains are official, so look-alikes of a brand are noticed and the official site is never flagged. Open `data/brands.yaml`, copy an existing entry and fill:

```yaml
  - brand_id: example_brand
    name_en: Example Brand
    name_ar: اسم العلامة
    category: bank
    verified_domains: [example-brand.ae]   # registrable domains only (eTLD+1)
    source_url: https://<where you saw these domains on the entity's own page>
    retrieved_at: 2026-11-23
    keywords_en: [example brand, card, account]
    keywords_ar: [اسم العلامة, بطاقة]
    logo_ref: null
    favicon_hash: null
    unverified_notes: ""
```

Rules: only add domains you verified on the organisation's own page and record the source and the date; omit anything unverified and explain it in `unverified_notes`. No logos or images in the repository. Then run `make test` and `make guard`. To add a whole new signal or Sentinel rule, follow the repository skills `.claude/skills/add-signal/SKILL.md` and `.claude/skills/add-sentinel-rule/SKILL.md` (signal file with a spec and tests; a rule entry in `services/sentinel/rules.yaml` with fire, no-fire and replay tests). Evidence weights live in `docs/SCORING.md`; changing a weight needs the maintainer.

### 4.9 Add a fixture

Fixtures are invented pages of **Falcon Demo Bank**, served only on the internal network. Each carries a visible "TEST FIXTURE, not a real site" label, and its forms post nowhere real.

1. Add the page under `services/fixtures/sites/<kind>/`.
2. Add a `server` block with a new `.test` host in `services/fixtures/conf/default.conf`, and add the host to `FL_SSRF_ALLOW_HOSTS` in `.env.example` and `docker-compose.yml` (the guard honours it only when `FL_ENV` is local, demo or ci).
3. `scripts/tests/test_fixture_hosts.py` keeps the lists in step; run `make test`.
4. Use only reserved names (`.test`, `.example`, `.invalid`). Never imitate a real organisation.

### 4.10 Run the local model with Ollama, and sovereign mode

```bash
ollama serve
ollama pull qwen3:4b
ollama pull qwen3-embedding:4b
```

The chat model for quality text is imported from local weights; follow `infra/ollama/README.md` (two `ollama create` steps, including the chat template file in `infra/ollama/`). Then in `.env`:

```bash
OLLAMA_BASE_URL=http://host.docker.internal:11434    # or the address of another machine
FL_SOVEREIGN_MODE=true
```

Apply it and verify:

```bash
make up
curl -sk https://localhost:8443/v1/meta        # reports sovereign_mode
```

In sovereign mode (or with no `ANTHROPIC_API_KEY`) every model role runs locally and no content leaves the machine. Look-ups (domain registration, certificate logs, feeds) still go out and carry domain names only; a switch to disable them is described in `docs/PRIVACY.md` but is not implemented in the code yet. A cold model load is slow; keep `OLLAMA_KEEP_ALIVE` long and let `make demo` pre-warm. Accuracy in sovereign mode is **not yet evaluated**.

### 4.11 Run the DSPy optimisation

{{DSPY}}

### 4.12 The 24/7 local worker

A small background program keeps local models busy with bulk jobs (synthetic messages, Arabic review, label passes, summaries). It talks only to Ollama, never calls a hosted API, never runs git and never edits tracked files. Its output is unreviewed and waits for a person.

```bash
make local-worker-run                  # foreground; Ctrl-C to stop
make local-worker-install              # macOS launchd agent: starts at login, restarts if it dies
make local-worker-status               # queue counts, heartbeat, last results
make local-worker-enqueue KIND=summarize INPUT=work/some.log
make local-worker-uninstall
```

Bulk drafting goes only through `scripts/qwen_task.py`. A task is refused if its input has a non-defanged `http(s)://` URL, points outside the repo, or names `.env` or `data/private`. More: `docs/LOCAL_WORKER.md`.

### 4.13 Run a second stack in parallel

```bash
COMPOSE_PROJECT_NAME=mine FL_GATEWAY_PORT=18443 FL_PROMETHEUS_PORT=19090 FL_GRAFANA_PORT=13001 make up
```

It has its own volumes, networks and host ports.

## 5. Public demo tunnel

```bash
make tunnel                     # needs cloudflared; prints "Public URL: ..." and saves it to data/private/tunnel_url.txt
# set FL_PUBLIC_BASE_URL=<that URL> in .env, then:
docker compose up -d api web
make tunnel-stop
```

Use the tunnel address, not `localhost`, when a client must trust the certificate (a phone, an MCP client). The tunnel file lives in `data/private/`, which is never committed.

## 6. The pull-request flow

1. Branch from `main`: `git switch -c feat/<module>-<slug>` (fixes: `fix/<module>-<slug>`).
2. Write the code **with its tests**. Log every assumption and every library version you adopt in `DECISIONS.md`, one line each. Read the library's current official documentation first.
3. Before you push: `make test`, `make guard` and, ideally, `make ci-local`.
4. Push and open the PR: `gh pr create`, and fill in the template. Propose any change to `contracts/` in the PR description instead of editing it; contracts are changed only by the maintainer.
5. CI runs lint, typecheck, test, contracts, security, docker-build and the eval gate. A reviewer writes `reviews/PR-<n>.md` with APPROVE or CHANGES REQUESTED. At most two review rounds.
6. After approval the maintainer merges, one PR at a time, with a squash merge. If your branch falls behind, update it (`git fetch origin && git merge origin/main`) and re-run the checks. Never merge your own PR and never force-push to `main`.

Roles and the local-model rules: `docs/HIERARCHY.md` and `CONTRIBUTING.md`. A human contributor's task list is in `docs/CONTRIBUTOR_TASKS.md`.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `make up` says Missing .env | first run | `cp .env.example .env` |
| "all predefined address pools have been fully subnetted" | Docker ran out of network address space after many stacks | `docker compose down`, `docker network prune`, and remove unused stacks; or widen Docker's default address pools in its daemon settings. A second stack on the same machine needs explicit subnets in an untracked compose override file |
| Port already in use | another service on 8443, 3001 or 9090 | set `FL_GATEWAY_PORT`, `FL_GRAFANA_PORT`, `FL_PROMETHEUS_PORT` in `.env`; `make urls` shows what is used |
| Browser certificate warning | local certificate authority | accept once; or use the tunnel |
| `429 Too Many Requests` | per-key or per-IP rate limit; the sandbox key is deliberately low | read the `Retry-After` header; create a key with a higher `--rate-limit`; raise `FL_RATE_LIMIT_PER_IP_PER_MIN` locally. Invalid-key attempts are limited per IP too |
| `401` | wrong or missing key | a key that is presented but wrong is rejected, not treated as anonymous |
| Verdict says "we could not complete every check" | the sandbox could not open the page, or a feed is disabled | this is deliberate and cautious; check `docker compose logs sandbox`, and that the `tools` profile is up for fixtures |
| Slow first answer with a local model | cold model load | pre-warm (`make demo` does it); keep Ollama alive |
| API or MCP refuses to start | `FL_ENV` is not `local` while a secret still starts with `change-me` | set real secrets or use `FL_ENV=local` |
| `make eval` fails | private datasets are not in the repository | run it on a machine that has `data/private/`; `make eval-gate` prints SKIPPED without data, which is not a pass |
| Smoke fails right after `make up` | a service is still warming | `scripts/wait_healthy.sh 300`, then `make smoke` |
| `make tunnel` fails | `cloudflared` missing | install it, retry |

Health endpoints: every service exposes `/healthz`, `/readyz` and `/metrics`.

## 8. Defensive-only rules

These are non-negotiable and enforced by `make guard`, `gitleaks` and review.

- **Defensive only.** Never register look-alike domains, never host or publish a page that imitates a real organisation, never message real people.
- **Passive visits only.** Suspicious pages are loaded only in the sandbox, once, passively. Never submit a form, never enter credentials, never scan beyond one normal visit.
- **Fixtures only.** Test pages use only the invented brand Falcon Demo Bank, carry a visible test label, post nowhere, and are served on the internal network or localhost.
- **No live data in the public repository.** No live phishing URLs, cloned-page snapshots or brand logos; those go in `data/private/` (gitignored). Publish only defanged URLs (`hxxp`, `[.]`), hashes, embeddings and aggregates.
- **Secrets only through the environment.** `.env` is never committed; the repository is public.
- **Truthfulness.** Every metric comes from a generated eval artifact. "Tools used" lists only what ships. Replayed or synthetic data is labelled everywhere. The lowest verdict is "No warning signs found", never a claim of harmlessness.
- **No endorsement.** Never claim an integration with, or the approval of, any police authority; use no police logos or branding. The wording is "ready to connect".
- **Respect feed licences** and rate limits.

## Appendix A. Every make target

{{MAKE_TARGETS}}
