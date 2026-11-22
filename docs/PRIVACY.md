# PRIVACY (handling description; not a legal compliance claim)

- **What we store.** The sha256 of the canonical input, defanged URLs, evidence and verdicts. Message and email bodies are **not** stored unless the user opts in to "report this".
- **Redaction** happens before logging and before any cloud LLM call. It covers UAE phone numbers (+971 and 05x), Emirates ID (784-YYYY-NNNNNNN-N), card numbers (Luhn-checked), emails and IBANs (AE..).
- **Cloud mode.** Redacted, spotlighted text goes to the Anthropic API for extraction, investigation and responses. Nothing else leaves the machine except lookups: RDAP, crt.sh and feeds, which carry domain names only.
- **Sovereign mode.** Every LLM call goes to the local Ollama, so no content leaves the machine. Lookups are still domain-only, and they can be disabled with `FL_OFFLINE_LOOKUPS=true`.
- **Retention.** Verdicts 30 days, then aggregated. Audit log is append-only. Snapshots are local only.
- **The product never asks for** personal, banking or ID details.
