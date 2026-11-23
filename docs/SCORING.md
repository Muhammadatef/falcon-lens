# SCORING: the deterministic arbiter

The arbiter is the only component that sets `risk_score`, `calibrated_probability` and `verdict`.
LLMs can add evidence through tools and can explain, but they cannot change the score.
Code: `packages/falcon_core/scoring/arbiter.py`. The weights below are the **initial draft**. `make fit-thresholds` fits the thresholds and bands **on the validation split only** and writes them to `packages/falcon_core/scoring/params.yaml`, with the dataset hash, git SHA and fit date.

## 1. Pipeline
1. **Hard rules** (§3) are evaluated first. A hard rule that fires sets the floor (or, for trust rules, the cap) of the verdict.
2. **Classifier probability `p_clf`**: a gradient-boosted model (T1 numeric features), calibrated with isotonic or Platt scaling on validation.
3. **Evidence log-odds adjustment** (each weight is scaled by the evidence `confidence`). Evidence from tiers above T1 (page, visual, brand, message, email, llm) has fixed weights `w_i` in log-odds points:
   `logit(p) = logit(p_clf) + Σ w_i · confidence_i`, clipped to [-8, 8].
4. `risk_score = round(100 · p)`. `calibrated_probability = p` after the final calibrator, fitted on validation over the full-cascade output.
5. **Bands**: `dangerous` if p ≥ τ_high; `suspicious` if τ_low ≤ p < τ_high; otherwise `no_warning_signs`.
   - Starting values: τ_high = 0.80, τ_low = 0.35. They are fitted so that FPR ≤ 2% and there are zero `dangerous` verdicts on the verified-official set (validation).
6. **Cascade exits**: T1 exits if p_clf < ε_low or p_clf > ε_high and there is no brand conflict. The low exit (to no_warning_signs) is allowed only when T1 found no url/domain/reputation risk evidence: a domain younger than 30 days, or a domain-age error that is not a configuration state, counts as risk and the input continues to T2 (2026-11-23, L1). T2 exits if a hard rule fired or p is outside [τ_low − 0.1, τ_high + 0.05]. Otherwise the input escalates to T3. ε values are fitted to keep T3 usage at 15% or less with no recall loss on validation.

## 2. Evidence weights (draft log-odds points; positive = risk)
| Signal | Family | w | Notes |
|---|---|---|---|
| rep.openphish / rep.gsb / rep.urlhaus hit | reputation | +6.0 | T0 exit when the mirror is fresh |
| url.homograph (skeleton matches brand, mixed script) | url | +3.0 | |
| url.typosquat (edit distance 1–2 to a brand domain) | url | +2.5 | |
| url.combosquat (brand token + pay/secure/track/…) | url | +2.0 | |
| url.brand_in_subdomain_or_path | url | +1.5 | |
| url.userinfo_trick / url.bidi_or_zero_width | url | +3.0 | |
| url.raw_ip_host | url | +1.5 | |
| url.data_uri | url | +2.0 | data: URI used as a link target |
| url.free_host_or_tunnel (PSL private section) | url | +1.0 | judged per subdomain |
| url.open_redirect_abuse | url | +2.0 | |
| domain.age_days < 30 | domain | +1.5 | <7 days: +2.5 |
| domain.cert_age_days < 7 | domain | +0.8 | |
| page.cred_form (password/card/CVV/OTP/EID/UAE Pass) | page | +1.5 | intent, not by itself proof |
| page.cross_origin_post (bot API/webhook/form relay) | page | +3.0 | |
| page.hotlinked_brand_assets | page | +2.0 | |
| page.cloaking (mobile-AR vs desktop differ) | page | +2.5 | |
| visual.favicon_match_brand | visual | +1.0 | only risk if domain not owned |
| brand.claimed_not_owned | brand | +3.0 | see H1 |
| message.script_match (nearest known scam, sim ≥ θ) | message | +2.5 | |
| message.scam_intent (fitted text model, p ≥ θ) | message | +4.0 × p | features: OTP/card ask, remote access, authority claim, payment ask, penalty, advance fee, off-platform, callback; weights fitted on train only (`intent_weights.json`) |
| message.rule.<name> for name ∈ urgency, secrecy, otp_request, remote_access, payment, authority, prize, job, investment, delivery_fee, fine | message | +0.6 each, cap +3.0 | evidence name is literally e.g. `message.rule.otp_request` |
| message.brand_mention | message | +0.5 | |
| message.brand_url_mismatch | message | +1.0 | brand named, link to unofficial domain |
| message.contains_url / message.contains_phone | message | 0 (informational) | children go to the URL pipeline (H5) |
| email.attachment | email | 0 (+1.5 if executable/script type) | type by magic bytes + sha256 only |
| email.return_path_mismatch | email | 0 (informational) | |
| email.invalid / image.invalid | email/image | 0 | sets degraded |
| image.qr_decoded | image | 0 (informational) | decoded URL is a child input |
| email.auth_fail (SPF/DKIM/DMARC fail) | email | +1.5 | |
| email.display_name_impersonation | email | +2.0 | |
| email.reply_to_mismatch | email | +1.0 | |
| email.link_text_mismatch | email | +2.0 | |
| message.link_verdict / email.link_verdict | message/email | 0 (informational) | child URL verdict; drives H5 |
| injection.instruction_like_text | injection | +1.5 | evidence of manipulation, **never obeyed** |
| registry.verified_official (domain in brand's verified list) | brand | −4.0 | see H3 |
| domain.age_days > 3650 + no other risk | domain | −1.0 | |

`page.js_obfuscation` and `page.anti_inspection` have no weight until a sandbox feature emits them (dropped from params.yaml, L1 2026-11-23).

Informational evidence with no weight (proposed by builder-signals; fingerprints for the Sentinel, not scored): `domain.cert_issuer` (latest CT cert issuer), `domain.ct_siblings` (other registrable domains on the same certs).

## 3. Hard rules
| Id | Condition | Effect |
|---|---|---|
| **H1 brand-mismatch (zero-day)** | claimed brand X from DETERMINISTIC signals (page title/visible-text brand tokens, favicon, hotlinked brand assets; never an LLM claim) with confidence ≥ θ AND page.cred_form or payment request AND registrable domain ∉ X.verified_domains | verdict = `dangerous`, p ≥ 0.95 |
| H2 known-bad | fresh feed hit (feed age < 6h) on the exact URL or host | `dangerous` |
| H3 verified-official | registrable domain ∈ a brand's verified list AND no open-redirect abuse AND no feed hit | verdict capped at `no_warning_signs` (never `dangerous`). Open redirects are judged on their target. |
| H4 exfil-to-bot | form or script posts credentials to a messaging-bot API or webhook relay | `dangerous` |
| H5 message-with-dangerous-link | message/email contains a URL whose verdict is `dangerous` (or `suspicious`) | message verdict ≥ the worst child link verdict: `dangerous` child → `dangerous`, `suspicious` child → ≥ `suspicious`; cites the child verdict evidence |
| H6 OTP/remote-access ask | message requests an OTP or a remote-access app install AND authority/bank impersonation | ≥ `suspicious` |

**Model cap (L1 D2, fitted on validation only).** The fitted T1 classifier alone never produces `dangerous`: its probability is capped `model_cap.margin` log-odds under `tau_high`, and `dangerous` without a floor rule needs `model_cap.strong_adj` log-odds of non-`url`, non-LLM risk evidence (and more than zero). Both values live in `params.yaml` (`model_cap`) and are fitted by `make fit-thresholds` (artifact `evals/results/published/fits/model_cap_fit.json`); the shipped fit chose margin 0 and strong_adj 0, i.e. "p ≥ tau_high AND any page/domain risk evidence". A model-driven warning cites a `url.classifier` evidence item so every warning has a reason. User-facing reasons are always evidence-grounded templates (the LLM never writes them).

Hard rules are evidence too: the triggering evidence carries `hard_rule: H1`, so the reasons can cite it.

## 4. Degradation
Signals carry a `criticality` (`SignalSpec.criticality`, default `critical`). **Critical** signal errors or timeouts at T0/T1 set `degraded=true` and list `signal_error:<signal>`. **Enrichment** signals (`domain.cert_age_days`/`cert_issuer`/`ct_siblings` from third-party crt.sh; any feed reporting `feed_disabled`; `domain.age_days` with `rdap_unsupported_tld`, `rdap_not_found` or `rdap_no_registration_date`, i.e. the registry holds no data) are informational: their errors stay in the evidence at weight 0 and **never** set `degraded`. Transient RDAP failures (timeout, HTTP errors) still degrade.

**Page not opened.** Egress/SSRF blocks (the SSRF guard at T0, the egress proxy's `X-Falcon-Block-Reason`, `blocked_by_policy`, redirect and size limits), the sandbox service's own errors (unreachable, `http_5xx`, bad response) and any unknown sandbox code **always degrade**. Only a failure that the browser-to-target leg alone can produce (`timeout`, `dns_failure`, `tls_error`, `http_403_empty` = an empty 403 from the target, `empty_response`) or a host that does not resolve at T0 is a *render failure*. A render failure ends in `no_warning_signs` only when ALL hold: T1 p < tau_low, no hard rule fired, no `url.*`/`brand.*`/`rep.*`/`domain.*` risk evidence (a domain younger than 30 days counts), AND there is page-independent trust evidence that did not error: `domain.age_days` above the established-domain threshold (3650 days, the trust row of section 2) or `registry.verified_official`. Then the verdict is `no_warning_signs` + caution, `degraded=false`, with informational evidence `sandbox.not_rendered` (weight 0): "We could not open the page itself; the address checks found no warning signs." / «تعذّر علينا فتح الصفحة نفسها؛ فحوصات العنوان لم تُظهر أي علامات تحذير.» Otherwise (young or unknown domain age, any risk) the verdict is degraded `suspicious` ("we could not open the page"): a page that refuses our browser on a domain we know nothing about is not cleared.

**A degraded verdict is never shown as `no_warning_signs`**: if p < tau_low and the input is degraded, show `suspicious` with "we couldn't complete every check" / «لم نتمكن من إكمال كل الفحوصات».

A URL scored without a fitted T1 probability (`p_clf` is None: the model is missing or failed) uses the draft fallback and is degraded with reason `t1_model_unavailable`, so it can never be no_warning_signs (contract invariant 4). Messages and emails have no T1 model and are not affected.

## 5. Explanations
The responder picks at most three reasons, ordered by |w|. Each must cite existing evidence ids. A verifier rejects anything else and falls back to the templates in `i18n/{ar,en}.yaml`.

## 6. Draft values (accepted 2026-11-22)
tau_*, eps_* and the T1 classifier are now fitted on validation (see `params.yaml` metadata); the evidence weights, hard-rule values and margins below remain draft.
ε_low 0.05 · ε_high 0.98 · H1 brand-claim θ 0.70 · H3 p cap 0.05 · draft intercept −2.2 (used only while `p_clf` is not yet fitted; flagged `p_clf_draft`).
Precedence: **degraded beats H3** (an official URL with a failed check shows `suspicious`). **H3 beats H1, H4 and H6** on verified-official domains; the overridden rules are recorded in `suppressed_rules`. The registry trust weight (−4.0) applies only when H3 holds.
Typosquat tiers (T-007): brand labels shorter than 5 characters get no edit-distance matching; 5–7 characters allow distance 1, or 2 if both edits are QWERTY-adjacent; 8 or more allow distance 2. The same label on a different TLD counts as `tld_swap` at confidence 0.8.
