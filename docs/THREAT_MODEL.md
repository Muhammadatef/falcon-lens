# THREAT MODEL (STRIDE) · v0.1 outline · owner: builder-security, reviewed by the supervisor

**Assets**:
- user inputs (they may contain PII)
- verdict integrity
- the host and internal network
- API keys and the operator key
- the LLM API key
- the public reputation of the project (it must never become a phishing host or a free fetcher)

**Adversaries**:
- phishing operators who craft pages to evade detection or attack the checker
- anonymous abusers of the public API
- malicious inputs aimed at the board or the logs

## Trust boundaries
1. Internet → gateway (anonymous public).
2. Gateway → api/mcp (authenticated integration keys, operator key).
3. Worker/sandbox → internet (fetching attacker-controlled content).
4. Untrusted content → LLM (prompt injection).
5. Stored attacker strings → web board (XSS).
6. Containers → host and Ollama.

## STRIDE
| | Threat | Mitigation | Test |
|---|---|---|---|
| **S** | Forged integration or operator key; spoofed webhook | argon2-hashed scoped keys; HMAC-signed webhooks (timestamp + 5-min replay window) | `tests/security/test_auth.py` |
| **T** | An injected page lowers its own score | Deterministic arbiter; LLM output can't touch the score; dual-model separation | `make redteam` (target 0%) |
| **T** | Feed or cache poisoning | Feed signature and format checks; cache keyed on the canonical URL hash | unit |
| **R** | Operator denies approving a takedown draft | Append-only `audit_log` (UPDATE and DELETE revoked) recording key id and evidence ids | db role test |
| **I** | SSRF to metadata, internal services or LAN | Own DNS resolution; block private, loopback, link-local, CGNAT, metadata, IPv6 ULA and mapped addresses; pin the IP for the connection; re-check every redirect; egress proxy as a second layer; sandbox network isolated | `tests/security/test_ssrf.py` (rebinding, redirects, decimal and octal IPs, IPv6, `@`-tricks) |
| **I** | PII leaks to the cloud LLM or logs | Redaction before cloud calls and before logging; message bodies not stored; sovereign mode | unit + log grep in CI |
| **I** | The checker used as an anonymous fetcher or proxy | Never return raw content; screenshots only for authenticated keys; per-IP limits | api tests |
| **I** | System prompt or canary exfiltration | Canary string in system prompts; output scan raises `fl_canary_leak_total` and an alert | redteam |
| **D** | Checker flooded; zip and decompression bombs; huge `.eml` files | Size limits (URL 4 KB, message 8 KB, email 2 MB, image 5 MB); decompression caps; per-IP and per-key limits; single-flight; sandbox pool limits | fuzz |
| **D** | Sandbox resource exhaustion | mem/cpu/pids limits; total timeout; one tab per context; kill and recycle | chaos test |
| **E** | Browser exploit escapes into the host | Sandbox runs as non-root with a read-only rootfs, `cap_drop: ALL`, `no-new-privileges`, seccomp default and tmpfs, on an isolated network; gVisor not used (not available on Docker Desktop for macOS); Chromium kept up to date | `docker inspect` checks in `make scan` |
| **E** | Stored XSS on the incident or campaign board | React escaping only; no `dangerouslySetInnerHTML`; strict CSP (`default-src 'self'`, no inline scripts, nonce-based); URLs displayed defanged and never as live links | Playwright XSS test with payload fixtures |
| **E** | Log injection | JSON logs; control characters escaped; field length caps | unit |
| **E** | Supply chain | Locked hashes (uv.lock, pnpm-lock); pip-audit, pnpm audit, trivy, gitleaks, semgrep; SBOM (syft) | `make scan` in CI |

## Prompt-injection specifics
- Untrusted text reaches **only** the quarantined extractor. That extractor has no tools and its output is a strict enum or short-string schema.
- Spotlighting: random nonce delimiters plus line datamarking. The system prompt says the content is data.
- The `injection.instruction_like_text` detector (regex + small classifier over multilingual phrases such as "ignore previous", «تجاهل التعليمات») adds risk evidence.
- Tool-argument provenance check (tools.schema.json `ProvenanceRule`).
- Budgets: 6 tool calls, 15 s and 8k output tokens per T3 run.

## Extension
MV3, with permissions `activeTab`, `storage` and `declarativeNetRequest`, and host permission only for the API origin. No remote code. Only the URL is sent.

## Residual risks (stated honestly)
- Docker Desktop on macOS gives VM isolation, but there's no gVisor.
- Phishing pages cloak against data-centre IPs, so the sandbox may see benign content. That's mitigated partly by the dual-profile load and the snapshot replay used in evals.
