# Falcon Lens | عدسة الصقر — project index

**Product.** An Arabic-first AI agent that protects UAE residents from scam links, fake websites, scam
messages and phishing emails, with an evidence-backed verdict in seconds. It has two agents:
- the **Investigator** judges one input. It is a tiered cascade T0–T3 with a deterministic arbiter, and an LLM is used only for the uncertain band.
- the **Sentinel** runs around the clock as a backend agent (LangGraph). It links checks into incidents and campaigns, triggers tools and alerts, and holds external actions until a human approves them.

It is an entry for Abu Dhabi Police x 42 "ScamShield AI", due **Wed 25 Nov 2026 08:00 GST**, with feature freeze **Tue 24 Nov 22:00**. The organiser rule: a working MVP or the entry is disqualified.

## Current phase
Phase 0, Foundation. See `STATUS.md` (gates), `TASKS.md` (task cards) and `DECISIONS.md` (assumptions and verified versions).

## Docs map
| Doc | What |
|---|---|
| `docs/VISION.md` | Problem, users, what "done" looks like |
| `docs/ARCHITECTURE.md` | Services, data flow, cascade, Sentinel pipeline, networks |
| `docs/adr/` | ADR-001 cascade+arbiter · ADR-002 Sentinel/LangGraph · ADR-003 local model · ADR-004 tunnel · ADR-005 event bus |
| `docs/HIERARCHY.md` | L0–L4 team, PR flow, local-model rules |
| `docs/CONTRACTS.md` + `contracts/` | Verdict, evidence, event, incident and tool schemas, OpenAPI. **Contracts are law.** |
| `docs/SCORING.md` | Arbiter features, weights, hard rules, bands |
| `docs/THREAT_MODEL.md` | STRIDE, SSRF, sandbox, injection, XSS |
| `docs/EVALS.md` | Datasets, splits, metrics, merge-gate tolerances |
| `docs/OBSERVABILITY.md` | `fl_` metrics, dashboards, alerts |
| `docs/INTEGRATION.md` | REST v1 + MCP for police systems ("ready to connect") |
| `docs/PRIVACY.md` | Data minimisation, redaction, cloud vs sovereign flow |
| `docs/RUNBOOK.md` | One entry per alert |
| `docs/DEMO.md` | Six scenarios, Sentinel scene, video shot list, pitch |
| `docs/research/VERIFIED_VERSIONS.md` | Library and API versions checked against official docs |

## Make targets
`up` `down` `smoke` `test` `eval` `redteam` `seed` `replay` `demo` `scan` `submission`.
Targets that aren't built yet must fail loudly with "not yet implemented"; they must never pass silently.

## Repo layout
```
services/api        FastAPI REST v1, SSE, auth, rate limits
services/worker     cascade orchestration (T0–T3), signals, arbiter
services/sandbox    Playwright browser service (isolated network)
services/egress     filtering egress proxy
services/sentinel   event consumer, correlation, rules, LangGraph agent
services/mcp        MCP server (streamable HTTP)
packages/falcon_core shared lib: contracts (pydantic), signals, scoring, llm router, tools
web/                Next.js PWA (Arabic-first RTL), incident board
extension/          Chrome MV3 extension
evals/              harness, datasets manifests, reports
infra/              grafana, prometheus, loki, alertmanager, otel, gateway
data/private/       GITIGNORED — live URLs, snapshots, logos
```

## Rules (non-negotiable; from the build prompt, Section 1)
**Truthfulness**
- Every metric shown anywhere comes from a generated eval artifact. Never type or estimate a number.
- "Tools used" lists only what the shipped code uses. Unfinished items go under Roadmap.
- Replayed or synthetic data is labelled as such everywhere, dashboards included.
- Never claim an integration with Abu Dhabi Police or imply endorsement. No ADP logos or branding. The wording is "ready to connect".

**Defensive-only**
- Never register lookalike domains. Never host or publish a page that imitates a real organisation. Never message real people.
- Suspicious pages are loaded only in the sandbox, passively. Never submit forms, never enter any credentials, never scan beyond one normal visit.
- Fixtures use only the invented brand **"Falcon Demo Bank"**. They carry a visible "TEST FIXTURE, not a real site" label, their forms post nowhere, and they are served only on the internal network or localhost.
- The public repo never holds live phishing URLs, cloned-page snapshots or brand logos. Those go in `data/private/`. Publish only defanged URLs (`hxxp`, `[.]`), hashes, embeddings and aggregates.
- Respect the licence and rate limits of every feed.

**Product behaviour**
- Never say "safe". The lowest verdict is "No warning signs found" / "لم نجد علامات تحذير", plus a caution reminder.
- Never ask the user for personal, banking or ID details.
- ADP reporting channels come only from the official site, stored in config with source URL and date. If unverified, show a generic line.

**Engineering**
- Read current official docs before coding against any API, library or model. Record the version in `DECISIONS.md`.
- Log every assumption in `DECISIONS.md`, one line each.
- The LLM never sets or changes a score; the arbiter does.
- All untrusted text is spotlighted (delimited and datamarked) before any model sees it. The investigator and Sentinel see structured evidence only.
- Secrets only through the environment. `gitleaks` runs in pre-commit and CI. **The repo is public.**

## Workflow
- L1 (main session) writes docs and contracts, dispatches builders, and merges only PRs the supervisor approved.
- Builders work on `feat/<module>-<slug>`, open a PR, and the supervisor reviews it (`reviews/PR-<n>.md`). Max two review rounds.
- Local-model jobs go only through `scripts/qwen_task.py` into `work/qwen/<task-id>/`. The supervisor audits a sample of at least 20% (minimum 30 items). An error rate above 5% rejects the batch.
- Skills live in `.claude/skills/`: `pr-review` `run-evals` `add-signal` `add-sentinel-rule` `qwen-task` `redteam` `demo-reset` `submission-check`.

## Conventions
- Python 3.12, uv workspace, ruff, mypy (strict in `packages/falcon_core`), pytest. TS uses pnpm, Next.js and strict mode.
- Every signal returns `Evidence[]`, never a verdict (`contracts/evidence.schema.json`).
- Every service exposes `/healthz`, `/readyz` and `/metrics`, and logs structured JSON carrying `verdict_id`.
- Arabic strings live in `packages/falcon_core/i18n/ar.yaml`, are written natively, and are short enough for a phone screen.
