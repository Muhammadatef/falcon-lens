# QWEN audit: qwen-msg-002 (synthetic_messages)

- Batch: `.claude/worktrees/agent-aadc0a0ffc4bb239f/work/qwen/qwen-msg-002/{output.jsonl,manifest.json}` (not committed). `output.jsonl` sha256 `e8519ce4…c491ec`
- Producer: `scripts/qwen_task.py` from PR #7 (`feat/evals-legit-and-qwen`, head `14a0a28`), model `inkling-2-mini-chat`, `structured_output: false`, seed 20261123, temperature 0.8, 75 calls, 1270.7 s
- Spec: `evals/specs/synthetic_messages_v2.json`, sha256 `9cf6c5c8…274204`. It matches both the manifest `spec_sha256` and the PR head file.
- Auditor: supervisor (L2) · 2026-11-22 · rule: docs/HIERARCHY.md (sample max(20%, 30), reject above 5% error)

## Verdict: **REJECTED**

**14 of 32** sampled items are wrong, an error rate of **43.8%** against a 5% limit. This batch is much better than qwen-msg-001 (96.9%):
- every label is correct;
- every link and phone follows the policy;
- the Arabic demo-brand name is correct;
- no item copies a few-shot example.

Two strata still fail.
- **Arabizi** is mostly English with nonsense digit-tokens added (6 of 7 sampled items are wrong).
- **Gulf Arabic** is often stuffed with dialect markers, uses Levantine or Egyptian forms, or doesn't make sense (6 of 11 wrong).

English (1 of 9 wrong) and MSA (1 of 5 wrong) are close to usable. Even so, the English and MSA sample together is 2/14 = 14.3% wrong, so I can't carve out a subset that passes either. **Don't import any item from this batch into `evals/`.**

## Checks on the full batch (n = 160)

Commands (all `python -I`, from `scratchpad/probes/`):
- `uv run --no-project --with jsonschema --with httpx python -I qwen_audit.py <output.jsonl> <spec v2> /tmp/fl-review-7/scripts <idx>`
- inline per-stratum and similarity one-liners (shown in the PR-7 session)

| Check | Result |
|---|---|
| Schema (`item_schema`, minus the added `synthetic/task_id/kind`) | 0 failures |
| `synthetic: true` on every item | yes |
| Spec `forbidden_patterns` | 0 hits |
| Links | 96 links, **0 non-conforming** (all `hxxps://example[.]test/<path>`) |
| Phone-like strings | **0** |
| UAE Pass / ICP outside `uae_pass_icp_impersonation` | **0** (only #130, #131, #132, #146 mention them, and all four are in that subtype) |
| Arabic brand name | Every Arabic mention is «بنك الصقر التجريبي». «فالكون» never appears |
| De-dup: 4-shingle Jaccard ≥ 0.8 within the batch | 0 pairs; 0 exact duplicates; 12 pairs at 0.6–0.8 (MSA `fake_fine` items are templated: #17/#35/#67 and others) |
| Copy of a few-shot example | max Jaccard 0.60 (#53, the "redelivery fee today to avoid return" template). No copies |
| Label × language cells | 24 per scam cell, 16 per legit cell |
| Manifest rejections | 223 generated → 59 rejected (arabizi digits 32, gulf marker missing 14, script 4, example copy 4, phone 3, entity 2) + 3 de-dup → 160 accepted |
| Marker stuffing | 27 of 40 Gulf items contain «هالحين», often with no sense of "now" (#16, #38, #66, #117) |
| Non-Gulf dialect forms in Gulf items (`رح\|هيتم\|بدي\|مش\|راح`) | 9 of 40 |

### Subtype skew (flag for evals reporting)
Overall: urgency 24, fake_fine 23, delivery_fee 21, bill_paid_receipt 16, appointment_reminder 14, bank_otp 11, statement_ready 10, service_outage 9, delivery_update 8, job 8, otp_notice 7, uae_pass_icp 4, investment 3, prize 2.

The skew is **confounded with language**:

| Stratum | Subtypes |
|---|---|
| scam · gulf_arabic | urgency 18/24 |
| scam · msa | fake_fine 21/24 |
| scam · english | delivery_fee 18/24 |
| scam · arabizi | bank_otp 11/24 |

The skew comes from the runner, not the model. `scripts/qwen_task.py:304` picks `variants[call_idx % len(variants)]` with a *global* `call_idx`. With 8 active strata and 8 scam variants, each stratum gets the same variant every round. Any per-language or per-subtype metric on such a batch would measure subtype, not language. Follow-up: TASKS T-029. Accepted batches must report subtype × language counts next to metrics.

## Sample

The sample seed is `int(sha256(output.jsonl)[:8], 16) = 3897662692`, drawn with `random.Random(seed).sample(range(160), 32)`, where k = max(⌈20% × 160⌉, 30) = 32. The seed is tied to the batch content, so it's reproducible but couldn't be known before generation. (Batch 001's seed 20261122 would have reused the same indices.)

| # | Declared stratum | Mark | Reason |
|---|---|---|---|
| 9 | legit · gulf_arabic · bill_paid_receipt | right | Correct receipt, no link. Realism is marginal (a stray «زين؟», MSA ending) |
| 10 | legit · msa · service_outage_notice | **wrong** | Text is a clinic appointment reminder sent by the bank. Subtype mismatch, and incoherent |
| 12 | legit · english · otp_notice_never_share | right | Says the code must never be shared, including with bank staff |
| 16 | scam · gulf_arabic · urgency | **wrong** | «هيتم إيقافه … ما تحققش» are Egyptian forms; «ابي أقولك وايد … زين؟» is marker stuffing, not Gulf speech |
| 17 | scam · msa · fake_fine | right | Formal MSA, generic «هيئة المرور», correct placeholder link |
| 22 | legit · gulf_arabic · otp_notice_never_share | right | Correct never-share notice; mostly MSA with a token «يالله» (marginal dialect) |
| 27 | legit · english · appointment_reminder | **wrong** | Policy: names a specific clinic ("Al Safa Clinic", a plausibly real Dubai business). The spec allows generic entities only |
| 35 | scam · msa · fake_fine | right | Formal MSA, generic «سلطة المرور», correct link |
| 38 | legit · gulf_arabic · appointment_reminder | **wrong** | Contradictory («هالحين الساعة ٤:٣٠»), «يالله نكون حاضرين» is incoherent, and it names a specific clinic «عيادة النخبة» |
| 39 | legit · gulf_arabic · appointment_reminder | right | Coherent enough reminder, no link. Marker stuffing («شلونك؟») is marginal |
| 43 | legit · msa · statement_ready_notice | right | Correct: statement ready in app, no link, no data request |
| 46 | legit · english · bill_paid_receipt | right | Correct |
| 47 | scam · gulf_arabic · urgency | **wrong** | «رح يتوقف … ما بتكمل» are Levantine forms; the opener «وايد هالحين!» is meaningless |
| 53 | scam · english · delivery_fee | right | Correct. Close to the few-shot template (Jaccard 0.60) but under the 0.7 copy threshold |
| 62 | legit · english · otp_notice_never_share | right | Correct |
| 66 | scam · gulf_arabic · urgency | **wrong** | Ends in nonsense («ابي أعرفك شلون هالحين؟ يالله يسرّع»): marker stuffing |
| 67 | scam · msa · fake_fine | right | Correct (templated with #17) |
| 83 | scam · gulf_arabic · urgency | **wrong** | «رح يتقفل» is Levantine; «الرابط هذي» has the wrong gender; not Gulf |
| 93 | scam · arabizi · bank_otp | **wrong** | Gibberish ("3indak OTP 3a 5,XXXXXX, enter 3oody … 3ashan n7ou2ak") |
| 94 | legit · gulf_arabic · appointment_reminder | right | Natural colloquial reminder, no link |
| 99 | legit · english · bill_paid_receipt | right | Correct |
| 102 | legit · arabizi · service_outage_notice | **wrong** | English with nonsense digits ("outage planned on 3, 7 and 5 … 3alik"); not Arabizi |
| 112 | scam · english · delivery_fee | right | Correct |
| 117 | legit · gulf_arabic · bill_paid_receipt | right | Correct receipt; the «هالحين:» opener is marginal |
| 119 | scam · gulf_arabic · job | **wrong** | Incoherent: the sender "wants a housemaid" («ابي شغالة») and says *they* must send *their* ID |
| 125 | scam · english · urgency | right | Correct |
| 133 | scam · english · prize | right | Correct, generic raffle |
| 139 | legit · arabizi · bill_paid_receipt | **wrong** | English plus nonsense ("Shukran, 3aak 7"); not Arabizi |
| 140 | legit · arabizi · bill_paid_receipt | **wrong** | English plus nonsense ("bill paid 3aak 9") |
| 145 | legit · arabizi · delivery_update_no_payment | **wrong** | English sentence with one nonsense token ("3atak"); not Arabizi |
| 149 | scam · arabizi · job | right | Plausible Arabizi and English code-switching ("n7tajlk ID copy w AED 100 upfront fee"); label correct |
| 152 | legit · arabizi · service_outage_notice | **wrong** | Gibberish ("3ish service slow 7asaab 2 ila 4"); the bank is the outage sender, but the spec says telecom provider |

Error rate: **14/32 = 43.8%**, above 5%, so the batch is **rejected**.

Per language in the sample:

| Language | Wrong |
|---|---|
| arabizi | 6/7 |
| gulf_arabic | 6/11 |
| english | 1/9 |
| msa | 1/5 |

## Root causes and what the next run needs
1. **The validators are now gamed rather than bypassed.** `language_rules.gulf_arabic.require_any` and the Arabizi `require_digit_letter` rule make the model insert «هالحين/زين/يالله» or "3a/3aak 7" tokens without writing the dialect. A validator can only check that markers are present, not that the dialect is real. Keep the rules; quality must come from the model and the audit.
2. **Gulf Arabic and Arabizi are beyond `inkling-2-mini-chat`.** For those two strata, either use a stronger local model (`gemma3:27b` / `qwen3.8:27b` when mirai is reachable; L1 to record), or have the owner write or curate them (L0). Next task id: `qwen-msg-003`. English and MSA can be re-run as their own task if L1 wants partial coverage, with a separate audit.
3. **Fix the subtype rotation first (T-029).** Otherwise the next batch is confounded the same way.
4. Add «عيادة/clinic + proper name» to the review checklist. The spec rule "generic entity names" isn't enforced for non-brand businesses; consider an `entity_rules` entry or a hint ("use 'the clinic'").
5. Any later batch that passes this audit still goes to the L0 Arabic spot-check (HIERARCHY L0).
