# QWEN audit: qwen-msg-001 (synthetic_messages)

- Batch: `.claude/worktrees/agent-aadc0a0ffc4bb239f/work/qwen/qwen-msg-001/{output.jsonl,manifest.json}` (not committed)
- Producer: `scripts/qwen_task.py` from PR-8 (`keep/feat/evals-legit-and-qwen`, `ab4b2d7`), model `qwen3:4b`, seed 20261122, temperature 0.9
- Spec: `evals/specs/synthetic_messages_v1.json`, sha256 `772a75eb…addd7`. It matches the manifest `spec_sha256` and the PR-8 branch file.
- Auditor: supervisor (L2) · 2026-11-22 · rule: docs/HIERARCHY.md (sample max(20%, 30), reject above 5% error)

## Verdict: **REJECTED**

**31 of 32** sampled items are wrong (96.9%, against a 5% limit). The failures are systemic, not borderline. The declared `language` doesn't match the text, MSA is written in English, the Gulf Arabic and Arabizi are incoherent, UAE Pass and ICP are named outside their permitted subtype, link placeholders are malformed, and a few-shot example was copied. Don't import any item from this batch into `evals/`.

## Checks on the full batch (n = 160)

Commands (all `python -I`, run from `scratchpad/probes/`):
- `qwen_audit.py <output.jsonl> <spec> <scripts dir> <idx out>`
- `qwen_stats.py <output.jsonl> <spec> <scripts dir>`

| Check | Result |
|---|---|
| Schema (`item_schema`, minus the added `synthetic/task_id/kind`) | 0 failures |
| `synthetic: true` on every item | yes |
| Spec `forbidden_patterns` | 0 hits (the blocklist is too weak; see below) |
| De-dup: 4-shingle Jaccard ≥ 0.8 between items | 0 pairs. Exact duplicate texts: 0. Pairs at 0.6–0.8: 22 |
| Copy of a few-shot example (Jaccard vs `spec.examples`) | **#64 = 1.0 (verbatim copy)**, #60 0.83, #5 0.71, #71 0.66, #73 0.66, #11 0.65 |
| Declared label × language cells | exactly 24 per scam cell, 16 per legit cell (by the declared field only) |
| **Actual script vs declared language** | **37 of 40 `msa` items aren't in Arabic script** (they are English) |
| UAE Pass / ICP named outside `uae_pass_icp_impersonation` | **25 items** (spec rule 1 allows them only in that subtype) |
| Link placeholders not exactly `hxxps://example[.]test/<path>` | **12** (`هxxps://…` ×9, `هكسبيس://…`, `Hxxps://…`, `?code=XXX` queries) |
| Phone placeholders | **#84 has `971 50 123 4567`** (real-format UAE mobile digits; spec rule 3) |
| Hint text copied into content | 19 items say "mokhalafa" (fine) in non-`fake_fine` subtypes |
| Subtype distribution | prize 3, uae_pass_icp_impersonation 3, fake_fine 6 vs delivery_fee 29 (very skewed) |

## Sample (seed `20261122`, `random.Random(seed).sample(range(160), 32)`, k = max(⌈20% × 160⌉, 30) = 32)

| # | Declared stratum | Mark | Reason |
|---|---|---|---|
| 4 | scam · english · delivery_fee | right | Label, language and placeholder link are correct. Realism is weak (a bank "releasing a parcel"), but it's acceptable |
| 9 | legit · gulf_arabic · bill_paid_receipt | **wrong** | Incoherent text ("يوم الأحمد في الحرب، والمدارس الحرامة"), heavy tashkeel, not Gulf dialect, not a receipt |
| 15 | legit · arabizi · delivery_update | **wrong** | Gibberish Arabizi ("3indak 7ab3i 3al a3mal 160 … 300 3arab 3a 92"), mixed with English |
| 35 | legit · english · appointment_reminder | **wrong** | Names UAE Pass outside the permitted subtype (policy) |
| 43 | scam · gulf_arabic · urgency | **wrong** | Garbled Arabic; link `هxxps://…` is malformed; content is a fine rather than urgency |
| 54 | legit · arabizi · service_outage | **wrong** | Mostly English; opens "3indak mokhalafa!" (you have a fine), which contradicts a legit outage notice |
| 56 | scam · gulf_arabic · urgency | **wrong** | Malformed link `هxxps://…` (spec rule 2); wording is closer to MSA than Gulf |
| 57 | scam · gulf_arabic · urgency | **wrong** | Nonsense opener ("مِلَّة تفاصيل"); malformed link; uses «بنك فالكون التجريبي», not the registry's «بنك الصقر التجريبي» |
| 58 | scam · gulf_arabic · urgency | **wrong** | Malformed link `هxxps://…`; semi-coherent |
| 60 | scam · english · delivery_fee | **wrong** | Near-copy of a few-shot example (Jaccard 0.83), same `/p1` path; the prompt says "do not copy" |
| 66 | legit · english · otp_notice_never_share | **wrong** | Not an OTP notice (it's a licence update), no "never share" line; subtype mismatch |
| 71 | scam · english · delivery_fee | **wrong** | Same template as the example and #60 (Jaccard 0.76 to #60), same `/p1` |
| 72 | scam · english · delivery_fee | **wrong** | "UAE Pass delivery update": UAE Pass outside its subtype (policy), and implausible |
| 76 | scam · arabizi · bank_otp | **wrong** | Gibberish ("4k 3600 kif 1234 mokhalafa, 500 aed 350"); `Hxxps` with a query |
| 86 | legit · arabizi · statement_ready | **wrong** | Written in English, not Arabizi |
| 92 | legit · gulf_arabic · appointment_reminder | **wrong** | Garbled ("الـمَلْحَمَة! انت تُخصَّص…"); UAE Pass outside its subtype |
| 94 | legit · gulf_arabic · appointment_reminder | **wrong** | Garbled ending ("لا تُرسل أرقامك لـالـتَّيَمَّل"); UAE Pass outside its subtype |
| 98 | scam · msa · urgency | **wrong** | English, not MSA; UAE Pass outside its subtype |
| 99 | scam · msa · urgency | **wrong** | English, not MSA |
| 100 | scam · msa · urgency | **wrong** | English, not MSA; content is a delivery fee, not urgency |
| 102 | scam · arabizi · fake_fine | **wrong** | Gibberish ("3h3b 3d 3mokhalafa 3l-3d 3d") |
| 111 | scam · msa · job | **wrong** | English; content is an OTP grab, not a job scam |
| 120 | scam · gulf_arabic · delivery_fee | **wrong** | Garbled Gulf Arabic ("امرارا توصيلك … مُحْتَجَّ"); a bank as courier |
| 126 | scam · msa · job | **wrong** | English, not MSA |
| 127 | scam · msa · job | **wrong** | English; content is UAE Pass ID renewal (wrong subtype, and policy) |
| 129 | scam · msa · job | **wrong** | English, not MSA |
| 132 | scam · arabizi · investment | **wrong** | Mostly English; "3indak mokhalafa" copied from the hint; incoherent |
| 135 | scam · arabizi · delivery_fee | **wrong** | Gibberish ("3indak 7mokhalafa, 15m3a7a b7a3l 3a3a") |
| 141 | scam · msa · urgency | **wrong** | English, not MSA |
| 145 | scam · msa · job | **wrong** | English; UAE Pass renewal in the `job` subtype (policy and subtype) |
| 149 | legit · msa · statement_ready | **wrong** | English; UAE Pass outside its subtype |
| 150 | legit · msa · service_outage | **wrong** | English, not MSA |

Error rate: 31/32 = 96.9%, above 5%, so the batch is **rejected**.

## Root causes and what a re-run needs (for builder-evals; tracked in reviews/PR-8.md)
1. `qwen_task.py` checks the model's *declared* `language` field, not the text. Add a script/language gate per stratum: Arabic-script ratio for `msa`/`gulf_arabic`, near-zero Arabic script plus Arabizi digit-letter markers for `arabizi`, and English otherwise.
2. The policy filter is a blocklist. Make links an **allow-list** (every link-like token must fully match `hxxps://example\[\.\]test/[A-Za-z0-9_/-]+`), make phones an allow-list (`+971 5X XXX XXXX` only; reject any run of 7+ digits with or without `+`), and add subtype-aware entity rules (UAE Pass/ICP only in `uae_pass_icp_impersonation`; Arabic real-brand names too).
3. De-dup against `spec.examples` as well as within the batch.
4. The spec gives the Arabic brand name «بنك فالكون التجريبي», but `data/brands.yaml` and `i18n/ar.yaml` use «بنك الصقر التجريبي». Use the registry name.
5. `qwen3:4b` can't produce usable Gulf Arabic or Arabizi. Re-run with a stronger local model (DECISIONS: `inkling-2-mini-chat`, or `gemma3:27b`) through `FL_LOCAL_WORKER_MODEL`. That choice is for L1 to record. Then re-audit with a new task id (`qwen-msg-002`).
6. Owner spot-check: any re-run batch that passes this audit should still get the L0 Arabic spot-check (HIERARCHY L0), because dialect quality is the main risk.
