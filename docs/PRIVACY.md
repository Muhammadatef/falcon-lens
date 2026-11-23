# PRIVACY (handling description; not a legal compliance claim)

- **What we store.** The sha256 of the canonical input, a defanged copy of each link checked, the evidence and the verdict. What a person pastes is **not** stored as such, and message and email bodies are not stored unless the user opts in to "report this".
- **Links that carry personal data.** A link can hold the recipient's details (`?email=…`, a phone number, an ID). The page is checked at the full address, but the copy that is stored, returned by the API and shown (`canonical_url`) has everything after the host passed through the same redaction as below, also when percent-encoded, and the fragment is dropped. Not covered yet: addresses inside evidence details (redirect chain, links found in a message) are defanged but not redacted.
- **Redaction** is applied to text before any cloud LLM call. Logs are separate: they escape control characters and carry no message bodies. Redaction covers UAE phone numbers (+971 and 05x), Emirates ID (784-YYYY-NNNNNNN-N), card numbers (Luhn-checked), emails and IBANs (AE..).
- **Cloud mode.** Redacted, spotlighted text goes to the Anthropic API for extraction, investigation and responses. Nothing else leaves the machine except lookups: RDAP, crt.sh and feeds, which carry domain names only.
- **Sovereign mode.** Every LLM call goes to the local Ollama, so no content leaves the machine. Lookups are still domain-only, and they can be disabled with `FL_OFFLINE_LOOKUPS=true`.
- **Retention.** A retention policy is planned (verdicts kept for a limited period, then aggregated) but it is **not yet automated**. The audit log is append-only. Snapshots are local only.
- **The product never asks for** personal, banking or ID details.
