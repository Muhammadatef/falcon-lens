# Contributor tasks: Abdulrahman (@Abdulrahman-alseiari)

Welcome to Falcon Lens | عدسة الصقر. The deadline is **Wed 25 Nov 08:00 GST** and the feature freeze is **Tue 24 Nov 22:00**.
These tasks were picked because they need a **human** (Arabic judgement, a real phone, manual verification) and **don't overlap** with the AI builders working in parallel. Read `CLAUDE.md` (the non-negotiable rules) and `CONTRIBUTING.md` (setup, branches, PR flow) first.

**How to work**
- Use one branch per task, named `feat/contrib-<task-id>-<slug>` (e.g. `feat/contrib-c01-arabic-review`), and open a PR to `main`. CI must pass, and the supervisor reviews it.
- Claim a task by putting your handle in the **Owner** column and opening a draft PR early.
- Never commit live phishing URLs, real people's numbers or messages, brand logos, or anything from `data/private/`. Use defanged URLs (`hxxps://example[.]test`) and the invented brand **Falcon Demo Bank / بنك الصقر التجريبي** in anything committed.
- Never put secrets in commits. `.env` stays local.

## Priority board

| ID | Task | Priority | Due (GST) | Owner |
|---|---|---|---|---|
| C01 | Arabic review of brand names and UI/verdict strings | **P0** | Mon 23 Nov 12:00 | |
| C02 | Verify the 5 weakly verified official domains | **P0** | Mon 23 Nov 12:00 | |
| C03 | Audit the synthetic Gulf Arabic / Arabizi messages | **P0** | Mon 23 Nov 14:00 | |
| C04 | Rate 20 Arabic verdict explanations (judge calibration) | P0 | Mon 23 Nov 18:00 | |
| C05 | 40 fictional phishing and legit `.eml` fixtures | P1 | Mon 23 Nov 20:00 | |
| C06 | More legitimate hard negatives (new domains, short links) | P1 | Mon 23 Nov 20:00 | |
| C07 | Real-device QA: Android PWA install and share target | P1 | Tue 24 Nov 12:00 | |
| C08 | iPhone Shortcut: share a link or text and get the verdict | P1 | Tue 24 Nov 16:00 | |
| C09 | Demo rehearsal and bug bash (all six scenarios) | P1 | Tue 24 Nov 18:00 | |
| C10 | Telegram bot (stretch) | P2 | only if every gate is green | |

---

### C01: Arabic review of brand names and UI/verdict strings (P0)
**Why:** answers must read natively and simply for an older Emirati reader. The AI wrote these strings and a native speaker must check them.

**Files:**
- `data/brands.yaml`: the `name_ar` fields. Most are marked "not confirmed".
- `packages/falcon_core/src/falcon_core/i18n/ar.yaml`: verdict, reason, action and caution templates. Arrives with PR `feat/core-arbiter`.
- Web app strings once `feat/web-app` lands.

**Do:**
- Correct each official Arabic name. Use the entity's own website or logo text as the source, and put that URL in the PR.
- Simplify any wording an older reader would struggle with.
- Flag anything that sounds like a guarantee. We never say «آمن» / "safe".

**Done when:** a PR changes only those strings, with a short table of before → after → reason. You can't edit files on another builder's branch before it merges, so open the PR against `main` after it merges, or comment on that PR.

### C02: Verify the 5 weakly verified official domains (P0)
**Why:** hard rule H3 trusts these domains completely. A wrong entry would whitelist an attacker, and a missing one would flag a real government or bank site.

**Domains:** `salik.ae`, `centralbank.ae`, `adcb.com`, `rakbank.ae`, `addc.ae` (and `taqadistribution.com`). They currently have only a basic DV certificate that doesn't name the owner.

**Do:** confirm each one from an official source: the entity's app-store listing developer site, a printed statement, a government directory (u.ae), or an official social account linking to it. Add any official domain we missed, such as a separate login or payment domain.

**Done when:** `data/brands.yaml` has `verification_l1` replaced by the evidence (source URL and date) for each, in one PR.

### C03: Audit the synthetic messages (P0)
**Why:** the local model generated 160 scam and legitimate messages for the eval set (task `qwen-msg-001`). They must be realistic, especially the Gulf dialect and Arabizi ones, and correctly labelled.

**Where:** ask Muhammad for the file. It lives in `work/qwen/qwen-msg-001/output.jsonl` and isn't committed. The supervisor's audit is in `reviews/QWEN-qwen-msg-001.md`.

**Do:** for a random sample of at least 40 items, add a JSONL line `{id, label_ok: bool, dialect_ok: bool, realistic_1to5, note}` to `evals/audits/qwen-msg-001.human.jsonl`. Also write 20 additional realistic Gulf Arabic scam messages yourself, using fake brands and placeholder links and numbers only.

**Done when:** the PR has the audit file and `evals/datasets/messages_human_v1.jsonl`, with `synthetic=false, author=human`.

### C04: Rate 20 Arabic verdict explanations (P0)
**Why:** the eval scores "Arabic clarity" with a judge model, which must be calibrated against a human (docs/EVALS.md).

**Do:** once `make eval` produces `evals/results/<ts>/arabic_samples.jsonl`, rate 20 items 1–5 on clarity, correctness and tone, using the rubric in docs/EVALS.md.

**Done when:** the PR adds `evals/audits/arabic_clarity.human.jsonl`.

### C05: 40 fictional `.eml` fixtures (P1)
**Why:** the email pipeline needs test and eval data.

**Do:** write 25 phishing and 15 legitimate emails in `.eml` format, all fictional.
- Senders use `@falcon-demo-bank.test`, `@example.test` and lookalike `.test` domains.
- Include SPF/DKIM/DMARC `Authentication-Results` headers (pass or fail), Reply-To mismatches, display-name spoofing ("Falcon Demo Bank Security"), link text that differs from the real href, and one with a QR code image (generate it; it should point to `hxxps://example[.]test/...`). Do this in Arabic, English and mixed.
- Labels go in `evals/datasets/emails/labels.csv`.

**Done when:** the PR adds `evals/datasets/emails/*.eml` and `labels.csv`, all parseable with Python's `email` module.

### C06: More legitimate hard negatives (P1)
**Why:** the legit set has only 5 "newly registered legitimate domain" rows and few shortened legitimate links. Without more, false positives are under-tested.

**Do:** add 30 or more legitimate new domains (registered 2024 or later; check with an RDAP or whois lookup and put the date in `source`) and 20 or more official shortened links (e.g. a company's own `aka.ms`/`youtu.be`-style links). Follow the columns in `evals/datasets/legit_urls.csv`.

**Done when:** the PR adds the rows, and each URL loads with one normal browser visit.

### C07: Real-device QA on Android (P1)
**Do:** when the web app is up (Muhammad shares the Cloudflare tunnel URL), install the PWA on an Android phone, share an SMS, a link and a screenshot to it, and check the verdict screen in Arabic and English, in dark and light themes.

**Done when:** you open GitHub issues (template "bug") with screenshots, and `docs/DEVICE_QA.md` has a table of phone and OS version, Chrome version, each test and pass or fail.

### C08: iPhone Shortcut (P1)
**Why:** iOS doesn't support PWA share targets, so iPhone users need a Shortcut.

**Do:** build an Apple Shortcut that takes shared text or a URL, sends `POST {tunnel}/v1/check/url` or `/v1/check/message` with `?wait=8`, and shows the verdict word, top reason and first action in Arabic. Export it as an iCloud link.

**Done when:** `docs/IOS_SHORTCUT.md` has the step-by-step build, screenshots and the iCloud link.

### C09: Demo rehearsal and bug bash (P1)
**Do:** follow `docs/DEMO.md` end to end from your own laptop. Use the remote setup Muhammad shares, or a fresh clone with `make demo`. Time each scenario and note anything that stalls, breaks or reads badly in Arabic.

**Done when:** issues are filed, plus a short `reviews/REHEARSAL-<date>.md`.

### C10: Telegram bot (P2 stretch, only if every gate is green)
**Do:** create `services/telegram-bot` (compose profile `stretch`). Forwarding it a message or link calls the API and replies with the bilingual verdict card. It uses `TELEGRAM_BOT_TOKEN` from `.env`, never committed, and stores no message bodies.

**Done when:** a PR with tests and a demo GIF.

---

## Don't touch (AI builders own these right now)
- `packages/falcon_core/src/falcon_core/{cascade,scoring,llm,agent,tools,signals,security,telemetry}`
- `services/{api,worker,sandbox,egress,sentinel,mcp}`
- `web/`, `infra/`, `docker-compose.yml`, `Makefile`, `contracts/`, `.github/workflows/`

If something there needs changing, open an issue and tag @Muhammadatef.
