# Tool logos for the pitch deck

Source: [Simple Icons](https://simpleicons.org) 16.38.1, licence CC0-1.0 (the icon files). Fetched 2026-11-25 from
`https://cdn.jsdelivr.net/npm/simple-icons@16.38.1/icons/<slug>.svg`, unmodified.

The marks themselves belong to their owners; the deck shows them only to identify the tools the shipped code uses,
with the footnote "Logos belong to their owners; shown to identify the tools used." No police mark, no bank or
consumer-brand logo is here or may be added.

`build_deck_v2.py` looks for a logo first in `web/public/logos/tools/` (the site's vendored set, when that branch is
merged) and then here. A tool with no file in either place gets a two-letter monogram badge, never a guessed logo:
DSPy, Kokoro, Amazon Polly, Arize Phoenix, Inkling, STIX, MLX and faster-whisper are monograms today.

| File | Tool it identifies in the deck |
|---|---|
| `openai.svg` | Whisper speech-to-text model (run locally) |
| `qwen.svg` | Qwen language and embedding models (run locally) |
| `claude.svg` | Claude models (cloud route) |
| `grafana.svg` | Grafana, and Grafana Loki |
| `docker.svg` | Docker Compose, and the sandbox container |
| the rest | the tool of the same name |
