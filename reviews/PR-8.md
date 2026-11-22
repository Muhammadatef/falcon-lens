# PR #8 review: feat/signals-message (message, email and image deterministic signals)

- Reviewer: supervisor (L2). Date: 2026-11-22. Round 1. Head `0af6814`, 0 commits behind `origin/main`.
- Worktree: scratchpad `wt8` (detached at `origin/feat/signals-message`), `uv sync --all-packages`, `.env` from `.env.example`.
- The repo was recreated, so this PR number was reused. The review of the former PR #8 (evals legit set and qwen runner) moved to `reviews/PR-8-former-evals.md`.

## Verdict: **CHANGES REQUESTED**

The structure is good:
- the email parser caps hold;
- the image decompression-bomb limit holds;
- QR decoding uses zxing-cpp;
- no network I/O happens in the email or image path;
- phones are masked;
- every emitted name is in SCORING §2;
- the fixture hosts are reserved TLDs.

Three correctness bugs in the Arabic path block the merge. The most serious one: a **legitimate Arabic bank OTP SMS triggers hard rule H6**, so it is forced to at least `suspicious`. That is the most common legitimate SMS in the UAE. The other two are an index-map crash in the normaliser and elongation not being normalised. The fixtures also name real police forces.

## Checks run

| Command | Result |
|---|---|
| `gh pr checks 8` | lint, typecheck, test, contracts, security, docker-build, eval-gate: all **SUCCESS** |
| `uv sync --all-packages && make test` | exit 0: ruff "All checks passed!", format "85 files already formatted", mypy "no issues found in 38 source files", pytest `406 passed, 1 skipped` |
| `uv run pytest packages/falcon_core/tests/contracts -q` | `10 passed` |
| `make eval-gate` | exit 0, but **SKIPPED**: "evals/baseline.json does not exist yet … This is NOT a pass" |
| `make scan` | exit 0: gitleaks "no leaks found", pip-audit "No known vulnerabilities found" (x2), trivy all targets 0. syft not installed locally (warn only) |
| `make guard` | `check_no_live_urls: ok` |
| `scratchpad/probes/pr8_msg.py` (Gulf, MSA, Arabizi and benign spot-checks, normaliser edge cases, ReDoS timing) | see findings 1-3, 6 and 7. ReDoS: 8 KB adversarial inputs (`a`*8192, `a.`*4096, `a-`*4096, digit runs, 60-char labels, long `http://`) run in 0.007-0.015 s each |
| `scratchpad/probes/pr8_email.py` (nesting, part cap, size cap, HTML with remote `<img>`/`<link>`, exe attachment, PNG bombs) | nesting 60/500 gives `too_many_parts`; nesting 3000 gives `parse_error:RecursionError` (caught); 200 flat parts give `too_many_parts`; 2 MB+1 gives `too_large`; tracker `<img>`/`<link>` are not extracted or fetched; exe attachment is typed `exe` by magic bytes with `risky`/`double_extension` set and only the sha256 kept; PNG 100000x100000 and 6000x5000 give `pixel_limit` in ≤16 ms; `Image.MAX_IMAGE_PIXELS` restored to 89478485 |
| `scratchpad/probes/pr8_names.py` (every non-url `spec.emits` vs `docs/SCORING.md`) | all 25 names present |
| `git diff origin/main...HEAD \| grep` for `httpx\|urllib\|requests\|socket\|urlopen` imports in src | none (exit 1) |
| URL and phone grep over the diff | test hosts are all `*.test`, `*.example` or `example.test`; phones are `050 000 0000`-style placeholders. The only real URL is `DECISIONS.md:45` (pre-existing ADP source URL) |

### Spot-check output (from `pr8_msg.py`)
```
legit_otp_ar "رمز التحقق الخاص بك هو 482913. لا تشارك هذا الرمز مع أي شخص. بنك الصقر التجريبي"
  -> secrecy ['لا تشارك'], otp_request ['رمز التحقق'], authority ['بنك'];  H6: ['message.rule.otp_request']
legit_gulf "حبيبي الحين انا في البنك، بعدين اكلمك عن الوظيفة الجديدة" -> urgency, authority, job
gulf_elong "عاااااجل!! حسابك بيتم تعليقه فووووراً" -> urgency only via 'بيتم تعليق' ('عاااااجل', 'فووووراً' missed)
norm elong: normalize("عاااااجل فووووراً").text == "عااجل فوورا"
'İİİİİİ urgent' -> EXC IndexError tuple index out of range
'ßßßß urgent now' -> urgency span (7, 13) == 'gent n'   (should be 'urgent')
benign_wheel "العجلة الأمامية للسيارة تحتاج تغيير" -> urgency ['عجل']
benign_email_word "ارسل لي على البريد الإلكتروني ملف الرسوم الدراسية" -> delivery_fee ['بريد','رسوم']
arabizi_otp "ramz el ta7a2o2 hwa 4821" -> no rules
gulf1/gulf2/gulf3, arabizi1/2/3 -> expected rules fire (urgency, otp, remote_access, authority, payment, prize, delivery_fee, secrecy); phones masked '+97150***00'
```

## Findings

### Blocking
1. **HIGH: H6 fires on legitimate OTP delivery messages.**
   - **What happens.** `_rule_evidence` (`message/analyze.py:98-117`) sets `hard_rule="H6"` whenever `otp_request` and `authority` both fire. Three lexicon entries make that true for ordinary bank SMS:
     - `authority` includes a bare `"بنك"`, `"مصرف"` (`message/lexicon.py:214-215`) and Arabizi `"[ae]l ?bank"` (`:237`), so any mention of a bank counts as impersonation;
     - `otp_request` matches the noun phrase `"رمز التحقق"` (`:90`), which is how a code is *delivered*, not an *ask*;
     - `secrecy` matches `"لا ?تشارك"` (`:60`), which is the standard anti-fraud warning.
   - **Effect.** The standard bank OTP SMS gets H6 (≥ `suspicious`, SCORING §3) plus +1.8 rule points. SCORING §3 defines H6 as "**requests** an OTP … AND authority/bank **impersonation**".
   - **Fix:**
     - (a) split OTP mention from OTP ask. H6 should key on an ask pattern, such as a send/share/tell verb plus the code (`ارسل/شارك/قول/عطني … الرمز/الكود`, `send/share/give/read me … code`), not on `رمز التحقق` alone;
     - (b) make `authority` an identity claim (`معك/هنا/من/نحن + <authority>`, `this is … police/bank`, or a registry brand token), not a bare `بنك`/`مصرف`/`el bank`;
     - (c) treat `لا تشارك (هذا )?الرمز` / `do not share (it|this code)` as an OTP-delivery marker that suppresses H6.
   - **Tests.** Add negative tests: the Arabic and English legitimate OTP texts above must not carry H6, and `legit_gulf` must not fire `authority`. Keep `test_h6_flag_otp_plus_authority` positive.
2. **MEDIUM: the index map goes out of step when one char expands.**
   - **What happens.** `normalize` (`message/normalize.py:64-73`) appends the result of `.translate`/`.casefold()` as one list element with one index. Any char that casefolds to two (`ß`→`ss`, `İ`→`i̇`, `ŉ`) makes `len(text) != len(index_map)`.
   - **Effect.** `find_rules("İİİİİİ urgent")` raises `IndexError`, and `"ßßßß urgent now"` reports the span `'gent n'`. `analyze_message` (the worker entry point) is not wrapped, so it raises. The registered signal degrades. Either way, an attacker can strip all rule evidence by appending a few `İ`.
   - **Fix:** `for c in folded: out.append(c); idx.append(i)`, and re-check the elongation and space logic per output char. Add tests with `İ`, `ß` and `ﷺ` that assert `len(text) == len(index_map)` and `text[a:b]` equals the matched word.
3. **MEDIUM: elongation is not normalised for Arabic.**
   - **What happens.** `normalize.py:70` collapses only 3+ repeats and keeps 2. Lexicon terms are single-letter, so `عاااااجل` becomes `عااجل` and `فووووراً` becomes `فوورا`, and neither matches. Elongation is a common Gulf SMS style.
   - **Wrong test.** `test_message.py:40` (`"هلااااا" -> "هلاا"`) locks the bug in.
   - **Fix:** for Arabic letters, collapse any run of 2+ identical letters to 1. Shadda is already dropped, so real doubled letters in Arabic script are rare. Keep the Latin rule of 3+ → 2 for English, and for Arabizi match with `+` or fold to 1 as well. Add elongated Gulf positives (`عاااجل`, `فوووورا`, `بسررررعة`).
4. **LOW: the fixtures name real authorities.** `test_message.py:71` ("This is Dubai Police cyber crime unit"), `:131` and `:139` ("شرطة ابوظبي") are impersonation scripts that name real police forces. CLAUDE.md:62 allows only Falcon Demo Bank in fixtures, and CLAUDE.md:59 forbids implying any ADP link. *Fix:* use generic wording ("هنا الشرطة", "This is the police cyber crime unit"). The lexicon terms are generic, so coverage is unchanged.
5. **LOW: `email.analyze` returns evidence that its spec does not declare.**
   - **What happens.** `email/analyze.py:40-48` declares only `email.*`. `run_email` also returns `image.*` (`:381-382`) and `message.rule.*`, `message.contains_*` and `message.brand_*` (`:402-403`). `contracts/signal.schema.json` `emits` says "Evidence signal names this plugin can emit".
   - **Risk.** `message.rules` declares `input_types` with `"email"`. If the orchestrator also runs it on an email's text, the message rules are counted twice.
   - **Fix:** either have `run_email` return only `email.*`, with `analyze_email` still exposing the message/image evidence and children to the orchestrator (record this in DECISIONS), or declare the extra names and drop `"email"`/`"image"` from the `message.*` specs' `input_types`.

### Non-blocking (fix by G1 or route to L1)
6. **Arabic matches have no word boundaries** (`message/rules.py:29-30` compiles `ar` bodies bare). As a result, `العجلة` (wheel) fires `urgency` via `عجل` (`lexicon.py:28`), and `البريد الإلكتروني … الرسوم الدراسية` fires `delivery_fee` via `بريد` + `رسوم`. Use a boundary that allows clitic prefixes, e.g. `(?<![ء-ي])(?:[وفبلك]?(?:ال)?)` before and `(?![ء-ي])` after (with suffix allowances where intended), and add these two as benign tests.
7. **Arabizi coverage gaps:**
   - `ramz el ta7a2o2` (the usual spelling of التحقق) folds to `tahaaoa` and misses `ta[hk]a?[qk]o?q`;
   - `bel bank` misses `[ae]l ?bank` (the lookbehind fails on `b`);
   - `bytm ta3leeq` has no urgency term.

   These matter for the EVALS Arabizi slice.
8. **Wording**: the `email.invalid` and `image.invalid` displays say "could not be processed **safely**" / «بأمان» (`email/analyze.py:206`, `image/analyze.py:67`). The project avoids "safe" in user-facing strings, so use "could not be processed" / «تعذرت معالجة البريد/الصورة».
9. **`email.attachment.name` is attacker-chosen free text in evidence** (`email/analyze.py:366`). It can carry PII (for example an ID number in the filename) or a host-like string that is not defanged. THREAT_MODEL row I says "message bodies not stored". Run it through `defang` and keep only the extension plus a hash of the name, or cap it to the extension.
10. **Image attachments are decoded.** `email/analyze.py:380-383` runs Pillow and zxing on image attachments. This is bounded by the 5 MB / 25 MP limits and recorded in DECISIONS, but the module docstring (`:5-6`, "never opened, decompressed") says otherwise. Fix the docstring. L1 should add one line to THREAT_MODEL row D.
11. **`message.script_match` reaches local Ollama through `ctx.http`** (`message/scripts.py:212-225`). `base.py:56` defines `ctx.http` as the SSRF-guarded external client, which blocks loopback and private addresses. Either the call will be refused in compose, or the guard has to be weakened. L1 should decide: either a dedicated local client on the context (an `embedder` or `local_http` with its base URL from config), or a guard allowlist for the configured Ollama host only. No live test was run (`DECISIONS`, builder note).
12. **Spans are not consistently "offsets into the original":**
    - for email, rule spans point into `subject + "\n" + body_text` (`email/analyze.py:402`);
    - `ChildInput.span` for URLs points into the de-obfuscated text (`extract.py:122,138`).

    Document this or map the spans back.
13. **Blocking work on the event loop:**
    - the sync bodies (email up to 1.5 s, image up to 2 s) run on the event loop, and `asyncio.wait_for` cannot preempt them (`base.py:118-122`, pre-existing);
    - the temporary global `Image.MAX_IMAGE_PIXELS` swap (`image/analyze.py:86-98`) will race once these move to `to_thread`. The explicit `width*height` check at `:92` already enforces the limit, so drop the global swap.

## Eval impact
- No `evals/results/` artifact. The eval gate is SKIPPED. No metrics are claimed in docs (the PR body's test counts match my run: 406 passed with main merged in).
- Expected effect before the fixes: false positives on legitimate OTP SMS (H6 forces ≥ `suspicious`) and on everyday Gulf text (bare `بنك`, `الحين`, `عجل` substrings). Elongated scam text is missed. All of these will show up on the EVALS messages set and hard negatives once they land.

## Requested for round 2
Fix 1-5 with the tests named above. 6-8 are strongly preferred in the same round. Route 10-11 to L1 and record them in DECISIONS.

