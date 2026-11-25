# False-alarm analysis: fresh-200 live test, legit set (2026-11-25)

Source: the stored verdicts and evidence rows of the fresh-200 run (artifact
`evals/results/published/fresh200/fresh200_0e91e66c04f8_20261124T143656Z.json`, run 2026-11-24). They were read once
with a read-only `SELECT` on the verdict store; nothing was re-checked and no behaviour was changed. Domains are
defanged. Legit set: 100 sites (80 Tranco, 20 official UAE). Result: 9 `suspicious`, 0 `dangerous`.

## Summary

| Root cause | Cases | Effect |
|---|---|---|
| A. The page was read only in part (`partial_render`) or the sandbox timed out (`sandbox_unavailable:timeout`), and no page-independent trust evidence was available, so SCORING §4 ("a degraded verdict is never shown as `no_warning_signs`") applies | 7 (risk 1–17) | degraded `suspicious` with no risk evidence at all |
| B. The fitted T1 URL classifier alone (`url.classifier` p_clf 0.67, at or above tau_low 0.6014) | 1 | `suspicious` before any page evidence; the read was also partial |
| C. `page.cross_origin_post` (+3.0) on a newsletter sign-up form posting to the publisher's sister domain, plus a partial read | 1 | risk 33; without the partial read it would have stayed below tau_low |

Why trust evidence was missing in root cause A: RDAP gives no registration date for `.io`, `.co`, `.ae` and `.cn` here
(`rdap_unsupported_tld`, 5 cases), or the domain is younger than the 3650-day trust threshold (3249 and 99 days, 2 cases).
In every one of the 9 cases, crt.sh was in back-off or failed (`crt_backoff`, `crt_http_502`, `crt_timeout`).
That is enrichment evidence, so it does not degrade the verdict by itself.

## Per case

| # | Domain (defanged) | Group | Risk | Degraded reason | Risk evidence (weight > 0) | Trust evidence | Root cause |
|---|---|---|---|---|---|---|---|
| 1 | sat24[.]com | legit_global | 67 | partial_render | none; `url.classifier` p_clf 0.67 | `domain.age_days` 9249 d (−1.0) | B |
| 2 | tomsguide[.]com | legit_global | 33 | partial_render | `page.cross_origin_post` basis=payload, targets on futureplc[.]com (newsletter) | none (age 9608 d, but other risk fired) | C |
| 3 | greenhouse[.]io | legit_global | 17 | sandbox_unavailable:timeout | none | none (`rdap_unsupported_tld`) | A |
| 4 | linuxserver[.]io | legit_global | 3 | partial_render | none | none (`rdap_unsupported_tld`) | A |
| 5 | primis[.]tech | legit_global | 1 | sandbox_unavailable:timeout | none | none (age 3249 d < 3650) | A |
| 6 | pixlee[.]co | legit_global | 1 | partial_render | none | none (`rdap_unsupported_tld`) | A |
| 7 | jumbo[.]ae | legit_uae | 1 | partial_render | none | none (`rdap_unsupported_tld`) | A |
| 8 | youth[.]cn | legit_global | 1 | partial_render | none | none (`rdap_unsupported_tld`) | A |
| 9 | moviessda[.]com | legit_global | 3 | sandbox_unavailable:timeout | none | none (age 99 d) | A |

The informational evidence seen on these pages carries weight 0: `page.truncated` (partial=true),
`page.cloaking_inconclusive`, `page.telemetry_beacon` and `llm.extraction` (no brand claimed, no instruction-like text).

## Reading

- 8 of the 9 false alarms are *degraded* verdicts: the product could not finish reading the page and does not clear
  what it could not read. This is the intended fail-closed rule (SCORING §4), not a detection error. The user sees
  "we couldn't complete every check", not a scam claim.
- Only 2 cases carry any risk signal: one model score (B) and one form-relay finding (C).
- None of the 9 is touched by this PR's changes (brand registry, UAE lure lexicon, H7). Possible follow-ups, all
  out of scope here and each needing its own held-out gate: an RDAP source for ccTLDs that the IANA bootstrap does not
  serve, a longer sandbox budget before a partial read is declared, and first-party/sister-domain handling for
  `page.cross_origin_post` newsletter forms.
- "UAE-targeted 1/20 warned" in the brief is this set's **legit** UAE group: that 1 is the false alarm in row 7
  (jumbo[.]ae, root cause A). It is not a phishing-recall number. The fresh-200 run had no UAE-targeted phishing group.
  UAE-targeted phishing recall is measured for the first time in `evals/results/published/uae_coverage/`.
