## What and why
<!-- One short paragraph. Link the task card (TASKS.md T-xxx) or issue. -->

## Changes
-

## Checklist
- [ ] Tests added or updated, and `make test` passes locally (ruff, mypy, pytest, web tests if `web/` changed)
- [ ] Contracts: `contracts/` is untouched, or the change is proposed below and the models, OpenAPI and tests match
- [ ] Defensive-only: no live phishing URLs, snapshots, brand logos or lookalike domains committed; fixtures use only "Falcon Demo Bank" and are labelled "TEST FIXTURE, not a real site"; nothing submits forms or messages real people
- [ ] No secrets: no keys, tokens or `.env` content (`make scan` is clean)
- [ ] No live URLs: any URL in `data/`, `evals/` or test fixtures is defanged (`hxxp`, `[.]`) (`make guard` passes)
- [ ] Truthfulness: no metric typed by hand; numbers come from a generated eval artifact; nothing says "safe"
- [ ] `DECISIONS.md`: assumptions and every library/image version used added, one line each
- [ ] Services: images multi-arch, non-root, HEALTHCHECK, `/healthz` `/readyz` `/metrics`

## Contract change proposals
<!-- None, or describe. -->

## Open risks
<!-- What could still break? -->
