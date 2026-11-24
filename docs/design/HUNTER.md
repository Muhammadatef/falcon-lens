# HUNTER — proactive early detection for the Sentinel «درع» (design)

Status: **design only, nothing in this document is shipped.** Owner request 2026-11-24. Implementation cards: `TASKS.md` T-033 … T-036.
Until those cards merge, no page, README line or deck slide may describe hunting as a product capability.

## 1. Goal and honest scope

Judging criterion: *Early Detection and Coverage (25%): catch threats before victims report them (newly registered domains, look-alike domains, fresh ads), covering search results and Maps listings (fake business pages, fake helpline numbers).*

Today the Sentinel only correlates checks that users submit. The hunt mode makes it look for candidates itself, then hands each one to the **existing** Investigator cascade. The hunt finds, the arbiter decides, the rules open incidents, a human approves actions. No new agent, no new scoring path, no LLM in the hunt loop.

| Coverage | Tonight | How |
|---|---|---|
| Look-alike domains of UAE brands | **live** | in-repo permutation generator + DNS existence check (DoH) |
| Fresh TLS certificate on a registered look-alike | **live, best effort** | crt.sh exact-identity lookup per candidate (measured working, slow, rate-limited; section 9) |
| Discovery of unknown names straight from Certificate Transparency | **experimental, off by default** | crt.sh substring search returned empty lists in every probe today (section 9); CT log tailing is Roadmap |
| Newly registered domains | **live** | existing `domain.rdap` age signal inside the cascade |
| Fake helpline numbers in messages and pages | **live once official numbers are verified** | number registry in `data/brands.yaml` + new evidence |
| Search results, ad libraries, Maps listings | **ready, needs API key** | adapter interface + capability flag; not polled, not claimed |

## 2. Data flow

```
 hunt.yaml + data/brands.yaml
        │
 ┌──────▼──────── Sentinel process (services/sentinel) ─────────────────────────────┐
 │ scheduler (every N min, kill switch, quotas)                                      │
 │   ├─ source: permutation ──▶ DNS existence (DoH)  ─┐                              │
 │   ├─ enrich: ct (crt.sh, exact name) ──────────────┼─▶ candidates ─▶ prescore ──┐ │
 │   └─ source: search|ads|maps (disabled, no key) ───┘   (hunt_candidates table)  │ │
 │                                                                                 │ │
 │   submit top-N within quota ─▶ POST /v1/check/url  channel=hunt  (hunt key) ◀───┘ │
 └───────┬──────────────────────────────────────────────────────────▲───────────────┘
         │ only via hunt-egress (allow: crt.sh, DoH host)            │ verdict.created on fl:events
         ▼                                                           │ (matched by verdict_id)
   internet                    api ─▶ fl:jobs ─▶ worker cascade T0–T3 + arbiter (unchanged)
                                                 RDAP, crt, sandbox single passive visit
 consumer: verdict for a hunt candidate ─▶ candidate.status ─▶ rules (R1, R2, new R6) ─▶ incident
           ─▶ LangGraph triage ─▶ drafts wait for human approval (unchanged)
```

Key decisions:
- **The Sentinel never contacts a candidate domain.** It talks only to crt.sh and the DoH resolver. Every contact with a candidate (RDAP, crt lookup, sandbox visit) happens in the worker, under the existing SSRF guard, budgets and passive-visit rules.
- **Submission goes through the public API path**, not a direct `XADD`. That reuses URL validation, single-flight, the verdict cache, rate limits and the audit trail. If the API answers `cached` or `attached`, a person got there first: the candidate is marked `already_known` and is never counted as found before a report.
- **Hunt does not publish `domain.observed`.** Verified in `services/sentinel/sentinel_core/rules.py:93`: a `not_in` condition passes when the feature is missing, so R1 would count unscored `domain.observed` look-alikes and open a campaign with no arbiter verdict. Candidates stay in `hunt_candidates`; only arbiter verdicts reach the rules.
- **Prescore is a queue priority, not a score.** It orders candidates and enforces the visit quota. It never appears as a risk score and never reaches the arbiter.

## 3. Components (files to create or change)

Pure logic, no I/O (`services/sentinel/sentinel_core/hunt/`):
| File | What |
|---|---|
| `permute.py` | dnstwist-style generator per brand `verified_domains` label: omission, repetition, transposition, adjacent-key replacement, hyphenation, homoglyph (from the vendored UTS #39 confusables used by `falcon_core/signals/url/skeleton.py`, output as punycode), combosquat (label ± `-` ± word, both orders; words reuse `COMBO_EN` / `COMBO_TRANSLIT` from `falcon_core/signals/url/squatting.py`), TLD swap (list in `hunt.yaml`). Typo and homoglyph variants only for labels of 5+ characters (`TYPO_MIN_LABEL`); short labels (du, rta, moi, dib) get combosquats only. Deterministic order, capped per brand. Drops any name whose registrable domain is a `verified_domain` of any brand. |
| `candidates.py` | `Candidate` model (section 4), dedupe on registrable domain, defanging, status transitions. |
| `prescore.py` | priority 0–100 from: discovery kind, permutation kind, has A, has MX, CT `not_before` age, brand category. Weights live in `hunt.yaml`. Documented as triage order only. |
| `tokens.py` | brand tokens for the CT query: registrable label of each verified domain, 5+ characters, minus `GENERIC_EN`. Read from the registry; no brand name in code. |

I/O (`services/sentinel/src/falcon_sentinel/hunt/`):
| File | What |
|---|---|
| `sources/base.py` | `HuntSource` protocol: `id`, `kind` (`ct` `permutation` `search` `ads` `maps`), `requires_key`, `terms_url`, `status()` → `live` / `ready_needs_key` / `disabled`, `async poll(brands, since) -> list[Sighting]`. |
| `sources/ct.py` | Two modes, one rate limiter (minimum gap `ct_min_interval_s`, 6 h cache, circuit breaker with exponential backoff on 429/5xx/timeout, 30 s timeout, response capped at 4 MB). **`ct_lookup` (on):** crt.sh `?q=<candidate>&output=json` for registered candidates, highest prescore first; yields `cert_first_seen = min(not_before)` and the reason `cert_fresh` when under 7 days. Reuses the parsing of `falcon_core/signals/domain/crt.py` (`summarize`). **`ct_search` (experimental, off):** `?q=%25<token>%25&output=json`, one brand token per call, round-robin. An empty list means "no data", never "no threat". The builder probes it once; if it still returns empty lists it ships disabled and `/v1/meta` reports it as `disabled`. |
| `sources/dns.py` | DNS over HTTPS JSON (`type=NS` on the registrable domain to test registration, then `A` and `MX` only for registered names). NS first, because wildcard and parking DNS make `A` alone meaningless. Token bucket `dns_qps`, negative cache 6 h, positive 1 h. |
| `sources/keyed.py` | `SearchSource`, `AdsLibrarySource`, `MapsListingSource`: interface and config parsing only; `status()` is `ready_needs_key` and `poll()` raises `SourceDisabled`. No HTTP code until a key and the provider terms are verified (section 8). |
| `sources/fixture.py` | reads a recorded CT-shaped JSON file (demo and CI). Every sighting carries `source=fixture`. |
| `http.py` | one `httpx` client bound to `FL_HUNT_PROXY`, built on `falcon_core.security.http`. No other client may be constructed in `hunt/` (test: grep + import check). |
| `store.py` | `hunt_candidates`, `hunt_source_state` (cursor, backoff, last success), `hunt_quota` tables; migration `services/sentinel/migrations/002_hunt.sql`. |
| `scheduler.py` | one cycle: check kill switch and quotas → poll enabled sources → dedupe → prescore → submit top-N → record. One asyncio task started in `main.py` `lifespan` next to `consume_loop`; Postgres advisory lock so two Sentinel replicas never hunt at once; cycle state is persisted, so a restart resumes and never re-submits. |
| `submit.py` | `POST /v1/check/url` with `channel: "hunt"` and the hunt key; stores the returned `verdict_id` on the candidate. |

Changes to existing code:
| File | Change |
|---|---|
| `services/sentinel/src/falcon_sentinel/consumer.py` | when a `verdict.*` event's `verdict_id` belongs to a candidate: set status, compute time-to-detection, set `origin="hunt"` on the features. The table is the authority; `payload.channel` is only a metric label. |
| `services/sentinel/sentinel_core/correlate.py`, `incidents.py` | `Features.origin`; incident `detection` block (section 4). |
| `services/sentinel/rules.yaml` | new **R6 `early_warning`**: `threshold`, `event_types: [verdict.created, verdict.upgraded]`, `where: {origin: hunt, verdict: dangerous, lookalike: true}`, `group_by: domain`, `min_count: 1`, `severity_floor: medium`, `merge_into: [R1]`. Fire, no-fire and replay tests through the `add-sentinel-rule` skill. A `suspicious` hunt verdict opens nothing alone; it still counts toward R1 and R2. |
| `services/api/src/falcon_api/app.py`, `auth.py` | `ChannelLit` gains `hunt`; new key scope `hunt`; `channel=hunt` from a key without that scope is rejected (422). Hunt checks are excluded from public history and from user-facing check counters. |
| `services/api/src/falcon_api/integration.py`, `intel.py` | `GET /v1/hunt/candidates` (public projection, section 6), `GET`/`PUT /v1/admin/hunt` (operator scope, audit-logged pause and resume), `hunt` block in `/v1/meta`. |
| `packages/falcon_core/src/falcon_core/signals/brands/contacts.py` + `signals/message/helpline.py` | official-number registry and the `brand.unofficial_contact_number` evidence (section 7). |
| `packages/falcon_core/src/falcon_core/telemetry/metrics.py` | metrics of section 5. |
| `docker-compose.yml` | `hunt-egress`: a third instance of the egress proxy image with `FL_EGRESS_DEST_ALLOW=crt.sh,<doh host>` on networks `[hunt, app]`, same pattern as `voice-egress`. The Sentinel gets `FL_HUNT_PROXY=http://hunt-egress:3128` and no general proxy variables. |
| `web/components/HuntFeed.tsx`, `web/app/campaigns/page.tsx`, `web/app/ops/page.tsx`, `web/app/api/public/hunt/route.ts` | section 6. |
| `infra/grafana/dashboards/6-sentinel.json`, alert rules, `docs/RUNBOOK.md` | section 5. |
| `docs/ARCHITECTURE.md`, `THREAT_MODEL.md`, `PRIVACY.md`, `OBSERVABILITY.md`, `DECISIONS.md` | updated in the same PRs that ship the behaviour, not before. |

## 4. Contract additions (contract-first; L1 applies them in T-033)

**Why not `source: "hunt"`.** `source` (`live|replay|synthetic|fixture`) is the truth label that CLAUDE.md requires on every event, incident and dashboard. A hunt result fed by a recorded fixture must stay `fixture`; a real crt.sh hit is `live`. Overloading the field would erase that. Hunting is therefore a separate dimension, **origin**.

- `contracts/verdict.schema.json`: `channel` enum gains `"hunt"`.
- `contracts/event.schema.json`: payload description gains `channel: hunt` and `hunt?: {candidate_id, discovery}`. No new event type.
- `contracts/incident.schema.json`:
  - `type` enum gains `"early_warning"`;
  - new optional `detection: {origin: "user"|"hunt"|"mixed", found_before_report: boolean, first_hunt_seen: date-time|null, first_user_seen: date-time|null}`;
  - `indicators[]` gains optional `found_by: "user"|"hunt"`.
  - `found_before_report` is true only when, for every domain indicator, the first event is a hunt verdict and no user-channel verdict or `report.submitted` for that domain is older. It flips to false, permanently, never the other way.
- `contracts/campaign.schema.json`: optional `found_before_report: boolean`, optional `hunt_count: integer`.
- New `contracts/hunt_candidate.schema.json` (`additionalProperties: false`):

| Field | Type | Note |
|---|---|---|
| `candidate_id` | `hc_<ULID>` | |
| `domain_defanged` | string | registrable domain, defanged; the live name is stored only in Postgres, never in the repo, logs or metrics |
| `domain_sha256` | string | |
| `brand_id` | string | from the registry |
| `discovery` | `ct` \| `permutation` \| `search` \| `ads` \| `maps` | |
| `permutation_kind` | `typo` \| `homoglyph` \| `combosquat` \| `tld_swap` \| null | |
| `reasons` | string[] | codes: `brand_token_in_cert`, `resolves_a`, `has_mx`, `cert_fresh`, `permutation:<kind>` |
| `provenance` | `{source_id, terms_url, retrieved_at, source: live\|fixture\|replay}` | where and when the sighting came from |
| `first_seen` | date-time | when the hunt first saw it |
| `upstream_seen` | date-time \| null | earliest certificate `not_before` from crt.sh, when known (the JSON rows carry no log-entry timestamp) |
| `prescore` | integer 0–100 | queue priority; operator view only |
| `status` | `new` \| `unregistered` \| `queued` \| `submitted` \| `confirmed` \| `cleared` \| `already_known` \| `skipped_quota` \| `error` | `confirmed` = arbiter said suspicious or dangerous |
| `verdict_id`, `verdict`, `incident_id` | string \| null | set by the consumer |
| `time_to_detection_s` | number \| null | section 5 |

- `contracts/openapi.yaml`: `GET /v1/hunt/candidates`, `GET`/`PUT /v1/admin/hunt`, `Meta.hunt = {enabled, paused, interval_min, sources: [{id, kind, status, terms_url}], last_cycle_at}`.

## 5. Config, metrics, alerts

`services/sentinel/hunt.yaml` (declarative, like `rules.yaml`; the LLM cannot edit it): sources with `terms_url`, combosquat words, TLD list, prescore weights, per-brand caps.

| Env | Default | Meaning |
|---|---|---|
| `FL_HUNT_ENABLED` | `false` | kill switch at deploy level; off means the task is never started |
| `FL_HUNT_SOURCES` | `permutation,ct_lookup` | add `fixture` in demo and CI; `ct_search` only after a successful probe |
| `FL_HUNT_INTERVAL_MIN` | `15` | cycle period |
| `FL_HUNT_CT_MIN_INTERVAL_S` | `120` | gap between crt.sh calls |
| `FL_HUNT_DNS_QPS` / `FL_HUNT_DNS_MAX_PER_CYCLE` | `5` / `1500` | DoH budget |
| `FL_HUNT_SUBMIT_MAX_PER_HOUR` / `_PER_DAY` | `20` / `200` | cascade (and so sandbox visit) quota |
| `FL_HUNT_PRESCORE_MIN` | `60` | below this a candidate is recorded, never visited |
| `FL_HUNT_PROXY` | `http://hunt-egress:3128` | the only route out |
| `FL_HUNT_API_KEY` | — | key with scope `hunt`, from the environment only |

Runtime pause: Redis key `fl:hunt:paused`, set from `/ops` through `PUT /v1/admin/hunt`, checked before every outbound request, audit-logged. `FL_SOVEREIGN_MODE=1` with `FL_OFFLINE_LOOKUPS=true` disables every network source.

Metrics (all carry `source` so replayed or fixture data stays labelled):
`fl_hunt_cycles_total{outcome}` · `fl_hunt_source_requests_total{source_id,outcome}` · `fl_hunt_candidates_total{discovery,source}` · `fl_hunt_submitted_total{source}` · `fl_hunt_confirmed_total{verdict,source}` · `fl_hunt_already_known_total` · `fl_hunt_quota_remaining{quota}` · `fl_hunt_enabled` · `fl_hunt_last_success_timestamp_seconds{source_id}` · `fl_hunt_time_to_detection_seconds{basis}` · `fl_hunt_lead_seconds`.

Two time measures, defined so they cannot be confused:
- **time to detection** = arbiter verdict time − the earliest upstream timestamp we hold: the earliest certificate `not_before` (`basis=cert_not_before`; approximate, CAs may backdate it slightly) or the RDAP registration date from the verdict's evidence (`basis=rdap`). Unknown basis → not observed. The UI names the basis next to the figure.
- **lead** = first user sighting of the same domain − hunt verdict time. Observed only when a person later submits it. On demo day this histogram will be nearly empty, and the UI must say "no user report yet" and never show a number.

Grafana `6-sentinel.json`, new row "Hunting | الرصد الاستباقي": candidates per hour by discovery, confirmed by verdict, time to detection p50/p95, quota remaining, source health. Alerts with runbook entries: `HuntStalled` (enabled, not paused, no successful cycle for 3 intervals), `HuntSourceBackoff` (a source in backoff for over 1 h), `HuntQuotaExhausted` (info).

## 6. UI

- `/campaigns`: section **"الرصد الاستباقي | Hunting"** (`HuntFeed.tsx`). Rows only for `confirmed` candidates: defanged domain as plain text (never a link), brand name, reasons as short localised phrases, first seen, status chip **«أكّده بصير»** / "Confirmed by Baseer" with the verdict, and **«رُصد قبل أي بلاغ»** / "Found before any report" only when `found_before_report` is true. Unconfirmed candidates appear as counts only, so a legitimate owner's domain is never listed as suspected.
- Above the feed: source chips from `/v1/meta` — live sources, and "جاهز، يحتاج مفتاح API | Ready, needs API key" for search, ads and Maps. A `fixture` row carries the same "TEST FIXTURE" label the boards already use.
- `/ops`: operator view with all statuses, prescore, quotas, pause and resume.
- Empty and error states are written; no number is shown that the API did not return. Wording never says "safe" / «آمن»; a cleared candidate reads "لم نجد علامات تحذير".
- Public route `web/app/api/public/hunt/route.ts` uses the server-side `read` key and the allow-list projection, like `public-history.ts`.

## 7. Fake helpline numbers (keyless, local)

- `data/brands.yaml`: optional `official_contacts: [{kind: phone, value: "+971…", label_en, label_ar, source_url, retrieved_at}]` per brand. Rule from T-006 applies: a number is added only when read on the entity's own page; otherwise it is omitted and noted. **Today the registry holds no numbers**, so the signal is inert until this data task is done (T-035).
- `brand.unofficial_contact_number` (T1 for messages, T2 for page text; local, no network): the text names a brand (existing registry match) and presents a UAE phone number (existing `extract_phones`) that is not in that brand's `official_contacts`. Evidence carries the masked number (`mask_phone`) and its sha256, never the number.
- A number that **matches** the registry emits nothing: caller ID can be spoofed, so a match is not trust.
- Scoring: `packages/falcon_core/scoring/params.yaml` is written only by `make fit-thresholds`. Tonight the evidence ships with weight 0 (shown as a finding, not scored). Giving it weight is a separate fit on train and val, owner-approved; the frozen test split is not touched.
- Brands with no verified numbers produce no evidence at all (no false alarm from an incomplete registry).

## 8. Search, ads, Maps: what is and is not claimed

Adapters exist as interfaces with `status = ready_needs_key`. Before any of them is implemented the builder reads the provider's current official docs and terms and records them in `DECISIONS.md`; none of the following was verified for this design (`unverified`): programmable search APIs need a key and have daily quotas; ad transparency libraries need an access token or have no public API; Maps or Places listings need a billing-enabled key. Scraping result pages is out: it breaks provider terms. `/v1/meta` and the website show these three as "ready, needs API key"; the README lists them under Roadmap.

## 9. Safety, privacy, risks

- **Defensive only.** Nothing is registered, no page is hosted, no one is messaged. The hunt adds no new kind of contact with a candidate: it uses the product's one normal passive sandbox visit, only above `FL_HUNT_PRESCORE_MIN`, only inside the hourly and daily quotas. No forms, no credentials, no crawling.
- **Egress.** New trust boundary "Sentinel → internet", closed to an allow-list of two hosts by `hunt-egress`. Responses from crt.sh and DoH are untrusted: size-capped, schema-validated, names normalised through the existing canonical and PSL code, never shown to an LLM as free text, defanged before display.
- **Privacy.** No personal data enters the hunt: inputs are brand names from our registry and public certificate and DNS data. Outbound lookups carry domain names only. `docs/PRIVACY.md` gains one line naming the DoH resolver and crt.sh. Helpline evidence stores masked numbers only.
- **Repo hygiene.** Real crt.sh recordings can contain live phishing hosts: they live in `data/private/hunt/` (gitignored). The committed fixture is hand-written in crt.sh's shape and names only `falcon-demo-bank*.test` hosts, marked TEST FIXTURE. CI runs with no network (sources mocked through `httpx.MockTransport`).
- **crt.sh is fragile (five probes, 2026-11-24 about 16:15–16:30 UTC, from the dev host).** Substring search `%25<token>%25` for two brand tokens: HTTP 200 with an empty list three times (2–4 s each) and HTTP 429 once, when a second call followed within seconds. Exact-identity lookup of one official domain: HTTP 200, 418 rows, 135 KB, 13.7 s; row fields `common_name, id, issuer_ca_id, issuer_name, name_value, not_after, not_before, result_count, serial_number`. Consequences: discovery rests on permutation + DoH; crt.sh is used per candidate; one call per 120 s with backoff and cache; substring search stays off until a probe returns rows. The DoH JSON endpoint answered in 0.6 s. crt.sh publishes no licence or rate limit that this design verified (`unverified`); the builder records the terms page and date in `DECISIONS.md` before enabling it, and it stays off if the terms forbid automated polling.
- **False accusations.** A look-alike name can belong to a legitimate owner. Mitigations: only arbiter-confirmed candidates are public; wording is "suspected"; actions stay drafts until a human approves.
- **Load on the product.** Hunt checks share the worker with users. The quota is the limit; submission stops when `fl:jobs` lag exceeds 20 entries, so a user check never waits behind the hunt.
- **Spoofed origin.** `channel=hunt` is accepted only from the `hunt` scope, and the Sentinel trusts its own table, not the label.
- **Honest numbers.** There is no hunt recall or precision figure and none may be typed. The UI shows live counters with their `source` label. An offline precision audit on a private CT sample is Roadmap.
- **Needs Opus review** (security invariants, rules, contracts, privacy): `hunt-egress` and the Sentinel's first egress, the `hunt` scope, R6, every contract change above, the PRIVACY line.

## 10. Demo script (register nothing)

1. `/ops`: hunting is paused. Show the source chips: permutation and certificate lookup live; search, ads, Maps "ready, needs API key".
2. Resume. The `fixture` source replays the committed CT-shaped fixture file: names on `falcon-demo-bank-*.test`. Narrate: "a certificate was issued a minute ago; no one has reported anything."
3. The feed shows the candidate, then the Investigator opens the fixture page in the sandbox (existing fixture hosts), the arbiter says dangerous, the row turns to «أكّده بصير», R6 opens an `early_warning` incident labelled TEST FIXTURE with «رُصد قبل أي بلاغ», and the takedown draft waits for approval. Approve it on stage.
4. One real query: run `ct_lookup` once on stage for one registered look-alike the live permutation source found (or, if none is registered that day, for one official brand domain to show the certificate history), and show the count and first-seen date, labelled `live` with the retrieval time. Expect 4–15 s. If crt.sh answers 429 or times out, say so and show the last private recording, labelled "recorded at <time>". Do not open any returned site by hand.
5. Grafana row "Hunting": candidates per hour, confirmed, time to detection.

Fallback if the stack misbehaves: steps 2–3 run fully offline (fixture source, fixture hosts).
