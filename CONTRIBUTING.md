# Contributing to Falcon Lens | عدسة الصقر

Thanks for helping. This is a defensive anti-scam project and the repo is **public**, so a few rules are strict.

## Non-negotiables (from CLAUDE.md)
- **No secrets.** Everything secret goes through `.env` (gitignored). Never paste keys in code, tests, issues or PRs. `gitleaks` runs in pre-commit and CI.
- **Defensive only.** Never register lookalike domains, never host or publish a page imitating a real organisation, never message real people, never submit forms or enter credentials on a suspicious page. Fixtures use only the invented brand **"Falcon Demo Bank"**, carry a visible "TEST FIXTURE, not a real site" label, and post nowhere.
- **No live URLs or private data in git.** Live phishing URLs, snapshots and brand logos live in gitignored `data/private/`. In tracked files use defanged URLs (`hxxp://`, `example[.]com`). `make guard` enforces this.
- **Truthfulness.** Every metric shown anywhere comes from a generated eval artifact; never type a number. Never say "safe": the lowest verdict is "No warning signs found" / "لم نجد علامات تحذير".
- **Contracts are law.** `contracts/` (JSON Schemas, OpenAPI) is changed only by the maintainer. Propose changes in your PR description.
- **The LLM never sets a score.** The deterministic arbiter does. Untrusted text is spotlighted before any model sees it.
- Log every assumption and every library/image version you adopt in `DECISIONS.md`, one line each.

## Setup
Requirements: Docker (Compose v2), [uv](https://docs.astral.sh/uv/), Node 24 + [pnpm](https://pnpm.io/) 12, `make`.

```bash
git clone https://github.com/Muhammadatef/falcon-lens && cd falcon-lens
cp .env.example .env            # all keys optional; empty keys disable the related feature
uv sync                         # Python 3.12 workspace
(cd web && pnpm install)        # web app
pre-commit install              # optional but recommended (ruff, gitleaks, hygiene)
```

## Make targets
| Target | What |
|---|---|
| `make up` / `make down` | start / stop core + obs and wait until every service is healthy |
| `make test` | ruff, ruff format check, mypy (strict on `falcon_core`), pytest |
| `make guard` | defensive-only guard (no live URLs, no `data/private`) |
| `make scan` | gitleaks, pip-audit, pnpm audit, trivy, syft (missing tool = warning) |
| `make eval-gate` | merge gate for detection quality (prints SKIPPED until `evals/baseline.json` exists) |
| `make smoke` `eval` `redteam` `seed` `replay` `demo` `submission` | all implemented; `make help` lists each with its description |

Web: `cd web && pnpm lint && pnpm typecheck && pnpm test`.

## Running a single service
```bash
docker compose --profile core up -d --build redis postgres api    # api and its deps only
uv run python -m falcon_api.main                                    # or run it on the host (needs REDIS_URL/DATABASE_URL for /readyz)
cd web && pnpm dev                                                  # web with hot reload
```
Run a second stack alongside another one with distinct ports and project name:
`COMPOSE_PROJECT_NAME=mine FL_GATEWAY_PORT=18443 FL_PROMETHEUS_PORT=19090 FL_GRAFANA_PORT=13001 make up`.

## Branches and pull requests
1. Branch from `main` as `feat/<module>-<slug>` (for example `feat/signals-domain`); fixes use `fix/<module>-<slug>`.
2. Keep PRs focused and add tests with the code. `make test` and `make guard` must pass locally.
3. Open a PR into `main` and fill in the template. CI runs `lint`, `typecheck`, `test`, `contracts`, `security`, `docker-build` and `eval-gate`; the first five are required, and no job needs secrets, so PRs from forks run fine.
4. One maintainer approval is required (CODEOWNERS). Review comments get addressed with new commits; stale approvals are dismissed on push. At most two review rounds.
5. Never merge your own PR and never force-push to `main`.

## Layout
`services/*` (api, worker, sentinel, mcp, egress, sandbox), `packages/falcon_core` (shared contracts, signals, scoring), `web/` (Next.js, Arabic RTL), `infra/` (gateway, Grafana, Prometheus, ...), `data/` (public registries only), `evals/`. See `docs/ARCHITECTURE.md`.
