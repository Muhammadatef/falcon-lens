# Verified versions and APIs (checked 2026-11-22)

Method: PyPI JSON API / npm view / Docker Hub + MCR tag APIs for versions; vendor docs via fetch for API shapes;
installed mcp, dspy, langgraph, playwright, fastapi, whoisit, confusable-homoglyphs in a scratch venv (Python 3.15)
to introspect signatures. "UNVERIFIED" = could not confirm from a primary source. Doc summaries came through a
fetch tool that summarizes pages, so quoted snippets are summaries, not byte-exact page text.

## 1. Claude Code config (checked 2026-11-22)
Source: https://code.claude.com/docs/en/sub-agents , /skills , /mcp

Subagent `.claude/agents/<name>.md` (project) or `~/.claude/agents/` (user). Only `name`, `description` required.
Unknown fields are ignored silently. Fields (camelCase, case-sensitive):
`name` (<=256 chars, no ':' / leading '-'), `description`, `tools` (comma string or YAML list; allowlist; omitted = inherit all),
`disallowedTools` (applied first, then `tools` resolved against the rest), `model`, `permissionMode`
(default|acceptEdits|auto|dontAsk|bypassPermissions|plan|manual), `maxTurns`, `autoCompactWindow` (>=100000, v2.1.296+),
`skills` (preloaded, <=32), `mcpServers`, `hooks` (PreToolUse/PostToolUse/Stop), `memory` (user|project|local),
`background`, `omitClaudeMd` (v2.1.271+), `effort` (low|medium|high|xhigh|max), `isolation: worktree`, `color`,
`initialPrompt`, `experimental.cacheTtl` (5m|1h).
- `model` values: aliases `sonnet`, `opus`, `haiku`, `fable`; a full id (e.g. `claude-opus-5-5`); or `inherit`.
- Restrict tools: `tools: Read, Grep, Glob` or `disallowedTools: Write, Edit`. MCP: `tools: mcp__server__*`; deny all MCP with `mcp__*`.
  `Bash(git push *)` inside `disallowedTools` removes ALL of Bash; use `permissions.deny` for command-level blocks.
  `Agent(a,b)` allowlist only applies to an agent run as main thread (`--agent`); ignored in subagent definitions.
- Plugin subagents ignore `permissionMode`, `mcpServers`, `hooks`.
```yaml
---
name: phish-reviewer
description: Reviews detector changes. Use proactively after edits under detectors/.
tools: Read, Grep, Glob
model: sonnet
maxTurns: 20
---
System prompt body here.
```
Skill `.claude/skills/<name>/SKILL.md` (only SKILL.md required; extras like reference.md, scripts/ optional).
Frontmatter (all optional, `description` strongly advised): `name`, `description`, `when_to_use`, `argument-hint`, `arguments`,
`disable-model-invocation`, `user-invocable`, `allowed-tools` (space-separated, pre-approves; does not restrict),
`disallowed-tools`, `model`, `effort`, `context: fork`, `agent`, `background`, `hooks`, `paths`, `shell`, `metadata`, `license`, `compatibility`.
```yaml
---
name: fix-issue
description: Fix a GitHub issue by number. Use when asked to resolve a specific issue.
argument-hint: [issue-number]
disable-model-invocation: true
allowed-tools: Bash(gh *) Read Edit
---
Fix GitHub issue $ARGUMENTS ...
```
`.mcp.json` HTTP (streamable) server with bearer header. `"type"` is mandatory (a `url` without `type` is treated as stdio and fails).
```json
{ "mcpServers": { "eaglelens": {
    "type": "http",
    "url": "${EAGLELENS_MCP_URL:-http://localhost:8000/mcp}",
    "headers": { "Authorization": "Bearer ${EAGLELENS_MCP_TOKEN}" } } } }
```
Env expansion `${VAR}` / `${VAR:-default}` works in command, args, env, url, headers. Do NOT name the var ANTHROPIC_API_KEY,
ANTHROPIC_AUTH_TOKEN, NPM_TOKEN etc. (read as empty in remote url/headers). CLI: `claude mcp add --transport http NAME URL --header "Authorization: Bearer X" --scope project`.

## 2. Anthropic Python SDK (checked 2026-11-22)
Package `anthropic` **2.12.0** (PyPI; Python >=3.10). Note major version 2.x. Sources: https://platform.claude.com/docs/en/about-claude/models/overview , /pricing , /build-with-claude/prompt-caching , /effort , /agents-and-tools/tool-use/define-tools , /build-with-claude/vision
- Model ids CONFIRMED: `claude-sonnet-5-5` (Sonnet 5.5, released earlier; retirement not before 2027-09-28), `claude-haiku-5-5` (released 2026-10-07; not before 2027-10-07). Both 1M context, 128K max output, text+image in, adaptive thinking. Opus is `claude-opus-5-5`, top tier `claude-fable-5-2`.
- Pricing per MTok (USD): 
  | Model | Input | Output | 5m cache write | 1h cache write | Cache read | Batch in/out |
  |---|---|---|---|---|---|---|
  | claude-sonnet-5-5 | 2 | 10 | 2.50 | 4 | 0.10 (0.05x) | 1 / 5 |
  | claude-haiku-5-5, prompt <=100k | 0.10 | 0.50 | 0.125 | 0.20 | 0.01 | 0.05 / 0.25 |
  | claude-haiku-5-5, prompt >100k | 0.50 | 2.50 | 0.625 | 1 | 0.05 | 0.25 / 1.25 |
  (Haiku 5.5 "From" pricing = tier by prompt length, counting cache tokens. New tokenizer: ~30% more tokens than pre-4.7 for same text.)
- Tool use shape (unchanged): `tools=[{"name","description","input_schema":{JSON Schema}}]`; response has `tool_use` blocks
  (`id,name,input`); reply with user message containing `{"type":"tool_result","tool_use_id":id,"content":"..."}`.
  **GOTCHA: Sonnet 5.5 (and Opus 5.5, Fable) return 400 for `tool_choice` `any`/`tool`** (forced tool use). Use `auto` + `strict: true` on tools, or structured outputs. Haiku 5.5 accepts forced tool use (skips thinking when forced).
- Thinking/effort: `output_config={"effort": "low|medium|high|xhigh|max"}`. Sonnet 5.5 default `high`; `thinking={"type":"disabled"}` is REJECTED (400); use `thinking={"type":"between_tools"}` (works at low/medium/high effort only). Haiku 5.5 default `medium`; `thinking={"type":"disabled"}` allowed at <=high. Omit temperature/top_p/top_k on Haiku 5.5.
- Prompt caching: `"cache_control": {"type":"ephemeral"}` (5 min) or `{"type":"ephemeral","ttl":"1h"}` on a system/content/tool block (longer TTL entries must come first). Min cacheable prompt: 512 tokens for Sonnet 5.5 and Haiku 5.5. Check `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens`. Changing `tool_choice` or top-level effort invalidates message-level cache.
- Image input:
```python
import anthropic, base64
client = anthropic.Anthropic()
r = client.messages.create(
    model="claude-haiku-5-5", max_tokens=1024,
    output_config={"effort": "low"},
    system=[{"type":"text","text":SYSTEM,"cache_control":{"type":"ephemeral","ttl":"1h"}}],
    messages=[{"role":"user","content":[
        {"type":"image","source":{"type":"base64","media_type":"image/png","data":b64}},
        {"type":"text","text":"Is this a phishing page?"}]}])
```
URL source (`{"type":"url","url":...}`) also exists for first-party API (UNVERIFIED exact shape; only base64 confirmed in fetched text). Limits: max 8000x8000 px per image; base64-only + 5 MB on Bedrock/Google-managed.

## 3. Ollama (checked 2026-11-22)
Docker image `ollama/ollama` latest 0.40.17 (amd64+arm64). Sources: https://docs.ollama.com/api/openai-compatibility , /capabilities/thinking , /api/embed , https://ollama.com/library/inkling-2-mini
- `/v1/chat/completions` supports: streaming, tools, vision (base64 only; image URLs NOT supported), JSON mode, `seed`, thinking control via `reasoning_effort` or `reasoning.effort`. NOT supported: `tool_choice`, logprobs, `n`, `logit_bias`, `user`.
- `/v1/embeddings`: model, input (str or list of str), encoding_format, dimensions.
- Native `/api/embed`: POST `{"model":"embeddinggemma","input":["a","b"],"truncate":true,"dimensions":N,"keep_alive":"5m"}` -> `{"embeddings":[[...],...],"prompt_eval_count":..}`.
- `inkling-2-mini` IS in the library: capability tags **vision, tools, thinking**; tags `latest`, `26b-a5b`, `26b-a5b-nvfp4` (MLX); ~20 GB; 1M ctx; Apache-2.0; text+image input.
- Disable/limit thinking: native `/api/chat` `"think": false` (or "low"/"medium"/"high"; models that cannot disable use lowest level; check `/api/show` -> `thinking.values`). OpenAI endpoint: `reasoning_effort`. Whether inkling-2-mini accepts `false` or which effort values it offers: UNVERIFIED (library page silent; run `/api/show` after pull).
```python
from openai import OpenAI   # openai 3.57.0
c = OpenAI(base_url="http://ollama:11434/v1/", api_key="ollama")
```

## 4. MCP Python SDK (checked 2026-11-22)
`mcp` **2.3.0** (Python >=3.10). BREAKING vs 1.x. Sources: https://py.sdk.modelcontextprotocol.io/ (run/asgi, run/authorization, migration), README.
- `FastMCP` renamed **`MCPServer`**: `from mcp.server import MCPServer` (also `mcp.server.mcpserver`; `mcp.server.fastmcp` now raises ModuleNotFoundError). Decorator `@mcp.tool()`.
- Transport options (`host, port, streamable_http_path, json_response, stateless_http`) are no longer constructor args; pass to `run("streamable-http", ...)` or `streamable_http_app(...)`. Pass everything after `name` by keyword.
- Client: `from mcp import Client; async with Client(url) as c: await c.call_tool(...)`; `streamablehttp_client` removed -> `streamable_http_client`; depends on `httpx2` (not httpx).
- Mount in Starlette/FastAPI (sub-app lifespan does NOT run; host must enter session manager):
```python
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Mount
from mcp.server import MCPServer
mcp = MCPServer("eaglelens")
@asynccontextmanager
async def lifespan(_):
    async with mcp.session_manager.run():
        yield
app = Starlette(routes=[Mount("/mcp", app=mcp.streamable_http_app(streamable_http_path="/"))], lifespan=lifespan)
```
  By default only localhost Host headers accepted; behind a real hostname you get 421 until you pass `transport_security=` allowlist to `streamable_http_app`/`run` (exact class name UNVERIFIED).
- Bearer auth: SDK's built-in path is OAuth resource-server style: `MCPServer("x", token_verifier=V(), auth=AuthSettings(issuer_url=AnyHttpUrl(..), resource_server_url=AnyHttpUrl(..), required_scopes=[..]))`
  with `from mcp.server.auth.provider import AccessToken, TokenVerifier`, `from mcp.server.auth.settings import AuthSettings`, and `async def verify_token(self, token) -> AccessToken | None`. `token_verifier` and `auth` must be passed together. 401s advertise RFC 9728 metadata. A static shared bearer can be implemented as a TokenVerifier comparing with `hmac.compare_digest` (needs a placeholder issuer_url), or as plain Starlette middleware in front of the mount (simpler; recommended for single-tenant).
- Constructor also has `lifespan`, `middleware`, `custom_route` (unauthenticated, for /health).

## 5. LangGraph (checked 2026-11-22)
`langgraph` **1.2.24**, `langgraph-checkpoint-postgres` **3.2.1**, `langchain-core` **1.8.4** (needs Python >=3.11). Sources: https://docs.langchain.com/oss/python/langgraph/interrupts , /persistence ; RetryPolicy via introspection.
```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command, RetryPolicy
from langgraph.checkpoint.postgres import PostgresSaver          # async: langgraph.checkpoint.postgres.aio.AsyncPostgresSaver
b = StateGraph(State)
b.add_node("tool_step", fn, retry_policy=RetryPolicy(max_attempts=3, initial_interval=0.5, backoff_factor=2.0, max_interval=128.0, jitter=True, retry_on=(httpx.HTTPError,)))
def approval(state): ok = interrupt({"question": "Approve?"}); return {"approved": ok}   # node restarts from top on resume
with PostgresSaver.from_conn_string(DSN) as cp:
    cp.setup()                       # once, creates tables
    g = b.compile(checkpointer=cp)
    cfg = {"configurable": {"thread_id": "case-123"}}   # <255 chars
    g.invoke(inp, cfg)               # result contains "__interrupt__"
    g.invoke(Command(resume=True), cfg)
```
Notes: checkpointer required for interrupt; never wrap `interrupt()` in bare try/except; RetryPolicy defaults (verified): initial_interval 0.5, backoff 2.0, max_interval 128, max_attempts 3, jitter True. `import langgraph.checkpoint.postgres` FAILS unless libpq/`psycopg[binary]` present (install `psycopg[binary,pool]`). Docs also recommend `stream_events(version="v3")` for interruptible graphs (UNVERIFIED details).

## 6. DSPy (checked 2026-11-22)
`dspy` **3.5.0** (Python <3.16). `litellm` 1.110.2 is NOT pulled in by default (DSPy 3.5 LM has `engine='auto'|'lm15'|'litellm'`); install `litellm` explicitly if you want it. Docs site fetch returned only a redirect stub, so signatures below come from introspecting the installed package.
```python
import dspy
lm = dspy.LM("anthropic/claude-haiku-5-5", api_key=KEY, max_tokens=1024, temperature=None)   # prefix style per LiteLLM; whether 'anthropic/' prefix is right under engine=lm15: UNVERIFIED
local = dspy.LM("openai/inkling-2-mini", api_base="http://ollama:11434/v1", api_key="ollama")   # OpenAI-compatible
dspy.configure(lm=lm)
class Triage(dspy.Signature):
    """Classify a URL/page as phishing."""
    page_text: str = dspy.InputField()
    verdict: str = dspy.OutputField(desc="phish|benign|unsure")
prog = dspy.ChainOfThought(Triage)        # or dspy.Predict(Triage)
```
Optimizers (verified signatures): `dspy.BootstrapFewShot(metric, metric_threshold, teacher_settings, max_bootstrapped_demos=4, max_labeled_demos=16, max_rounds=1, max_errors)` -> use for <~50 examples.
`dspy.MIPROv2(metric, prompt_model, task_model, auto='light'|'medium'|'heavy', num_candidates, num_threads, max_bootstrapped_demos=4, max_labeled_demos=4, seed=9, ...)`; `.compile(student, *, trainset, valset=None, num_trials, minibatch=True, ...)` -> prefer with ~200+ examples (general DSPy guidance; docs page itself UNVERIFIED).
Save/load: `compiled.save("prog.json")` (state only, JSON; `save_program=True` saves whole program dir), `prog2 = Triage_Module(); prog2.load("prog.json")`. `load(path, allow_pickle=False, allow_unsafe_lm_state=False)` - keep the defaults (safe).

## 7. Playwright for Python (checked 2026-11-22)
`playwright` **1.65.2** (PyPI). npm `@playwright/test` 1.65.1. Docker: `mcr.microsoft.com/playwright/python:v1.65.2-noble`; MCR lists per-arch tags `-noble-amd64` and `-noble-arm64` (arch list from tag names; manifest-list multi-arch of the bare tag UNVERIFIED but per-arch tags exist). Docs page still showed v1.64.1 examples (docs lag). Source: https://playwright.dev/python/docs/docker , /emulation , /network
- Pin library version == image version. Run with `--init --ipc=host`; image runs as root (Chromium sandbox off) -> for untrusted sites run as `--user pwuser` with the seccomp profile from the docs.
- Verified `Browser.new_context` kwargs exist: `locale, timezone_id, user_agent, java_script_enabled, accept_downloads, service_workers, bypass_csp, permissions, offline`.
```python
ctx = browser.new_context(**p.devices["iPhone 13"], locale="ar-AE", timezone_id="Asia/Dubai",
                          accept_downloads=False, service_workers="block", java_script_enabled=True)
BLOCK = {"image", "font", "media"}
ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in BLOCK else r.continue_())
```
- Download blocking: `accept_downloads=False` (kwarg verified by introspection; behavior text not on the fetched page -> semantics UNVERIFIED, test that a download trigger does not write a file). Pass `user_agent=None` with a device dict to keep platform UA.

## 8. FastAPI / SSE / pydantic (checked 2026-11-22)
`fastapi` **0.165.0** (Python >=3.11), `starlette` 1.10.0, `pydantic` **2.14.4**, `uvicorn` 0.54.0, `sse-starlette` **3.7.0**, `httpx` 0.28.1.
FastAPI now has native SSE: module `fastapi.sse` exports `EventSourceResponse`, `ServerSentEvent`, `format_sse_event`, `KEEPALIVE_COMMENT` (verified by import). Exact generator/`response_class` usage UNVERIFIED (not read from docs); sse-starlette 3.7.0 remains a safe fallback: `from sse_starlette.sse import EventSourceResponse`.

## 9. pgvector / psycopg (checked 2026-11-22)
Docker `pgvector/pgvector:0.8.7-pg18-trixie` (also `pg18`, `0.8.7-pg17`, `pg17`; amd64+arm64; pushed 2026-11-12). Recommend pin `pgvector/pgvector:0.8.7-pg18-trixie` (or `0.8.7-pg17-trixie` if you want 17). Official `postgres:17.12` also multi-arch.
Python: `pgvector` **0.5.1**, `psycopg` **3.3.9** (install `psycopg[binary,pool]`). Snippet (standard API, not re-read from docs): `from pgvector.psycopg import register_vector; register_vector(conn)` after `CREATE EXTENSION vector`. LangGraph's PostgresSaver uses the same psycopg 3.

## 10. Next.js / PWA (checked 2026-11-22)
`next` **16.4.6**, `react` 19.3.1 (npm). Source: https://nextjs.org/docs/app/guides/progressive-web-apps (updated 2026-07-30), https://caniuse.com/mdn-manifests_webapp_share_target , MDN share_target.
- `share_target`: Chrome for Android supports (Chrome 89+; caniuse says through 151); only works when the PWA is INSTALLED. **iOS Safari: NOT supported** (caniuse lists no iOS support through 27.x entries; WebKit bug 194593 open, no assignee). Outbound `navigator.share` works on iOS. So on iOS use paste box / Shortcuts / share-extension alternatives. Also MDN marks it experimental/non-Baseline.
```ts
// app/manifest.ts
export default function manifest(): MetadataRoute.Manifest {
  return { name: "Eaglelens", short_name: "Eaglelens", start_url: "/", display: "standalone", icons: [...],
    share_target: { action: "/share", method: "GET", params: { title: "title", text: "text", url: "url" } } } }
```
(GET share_target is not in Next's `MetadataRoute.Manifest` typing guarantees: UNVERIFIED; may need a cast or static `app/manifest.json`.) Use GET so no SW handling is needed; POST/files requires a fetch handler in the SW and a 303 redirect.
- Service worker without plugins: put `public/sw.js`, register in a client component `navigator.serviceWorker.register("/sw.js", {scope:"/", updateViaCache:"none"})`; add `headers()` in next.config for `/sw.js` (`Cache-Control: no-cache, no-store, must-revalidate`, `Content-Type: application/javascript; charset=utf-8`, CSP `default-src 'self'; script-src 'self'`). Docs example registers `new URL('../lib/service-worker.js', import.meta.url)`. Serwist is the doc-named option for full offline caching. Install prompts: iOS needs manual "Add to Home Screen"; `beforeinstallprompt` is not cross-browser. Push on iOS needs 16.4+ and installed app.

## 11. Chrome Manifest V3 (checked 2026-11-22)
Sources: https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest , /develop/concepts/activeTab , /declare-permissions
- DNR redirect to a bundled warning page: rule action `{"type":"redirect","redirect":{"extensionPath":"/warning.html"}}`; `warning.html` must be in `web_accessible_resources`. Limits: 30,000 dynamic rules (5,000 "unsafe"), 5,000 session rules, 1,000 regex rules per type, regex <2KB, 50 enabled static rulesets (>=30,000 static rules guaranteed). Needs `declarativeNetRequest` permission plus host permissions for redirect (or `declarativeNetRequestWithHostAccess`; these two permission names are standard but were not on the fetched page -> UNVERIFIED here).
- DNR is static/list-based: fine for known-bad lists, cannot call your API per navigation. Per-URL verdicts need `chrome.webNavigation`/`tabs.onUpdated` in the service worker + `fetch` to API, then `chrome.tabs.update(tabId, {url: chrome.runtime.getURL("warning.html?...")})` or inject an interstitial via content script (needs host permission).
- Minimum permissions to read the current tab URL: `activeTab` (temporary, only after user gesture such as clicking the action; URL/title/favicon readable; ends on cross-site navigation; no install warning). Without a gesture (automatic checks) use `tabs` permission (URL access without host permissions per fetched docs) or host permissions (broad warning). Recommended design: `permissions: ["activeTab","declarativeNetRequest","storage"]` for on-click check + DNR blocklist; add `webNavigation` + `tabs` only if auto-checking is required.

## 12. LLM tracing (OTel) (checked 2026-11-22)
- **Arize Phoenix**: single container `arizephoenix/phoenix:version-22.0.1` (Docker Hub, amd64+arm64; PyPI `arize-phoenix` 22.0.1; also `-nonroot` variants). Ports 6006 (UI + OTLP/HTTP at `/v1/traces`), 4317 (OTLP gRPC). Storage: SQLite on volume (`PHOENIX_WORKING_DIR=/mnt/data`) or Postgres via `PHOENIX_SQL_DATABASE_URL` (PG >=14). Auth env vars: UNVERIFIED (not on fetched page).
- **Langfuse**: `langfuse/langfuse:3.227.1` image on Docker Hub (arm64+amd64); SDK `langfuse` 5.2.0. Self-host needs web + worker + Postgres + Redis/Valkey + ClickHouse (`clickhouse/clickhouse-server:26.9.35.9`) + S3/blob. Docs page I got was labeled v4 so exact current server version/required-components for v3 vs v4: UNVERIFIED. Heavy for a small stack.
- **Jaeger** `jaegertracing/jaeger:2.23.0` (arm64+amd64): lightest generic OTel trace store, but no LLM-specific UI.
- **Recommendation: Phoenix** (one container, reuse the existing Postgres or SQLite volume, native OTLP, OpenInference/LLM-aware UI). Pin `arizephoenix/phoenix:version-22.0.1-nonroot`. Skip Langfuse unless you need prompt mgmt/evals/multi-user.

## 13. Pinned multi-arch images (arch lists from Docker Hub API, 2026-11-22)
| Service | Tag | Arch |
|---|---|---|
| redis | `redis:8.8.4-alpine` (8.12-rc3 exists: RC, avoid) | amd64, arm64 (+more) |
| prometheus | `prom/prometheus:v3.16.0` | amd64, arm64 |
| alertmanager | `prom/alertmanager:v0.35.0` | amd64, arm64 |
| grafana | `grafana/grafana:13.2.6` (13.1.10 also) | amd64, arm64 |
| loki | `grafana/loki:3.7.10` (3.6.22 on older line) | amd64, arm64 |
| log shipper | **Alloy** `grafana/alloy:v1.22.0` (amd64, arm64). **Promtail is EOL since 2026-03-02**; Alloy is the replacement (migration tool exists) | |
| otel-collector-contrib | `otel/opentelemetry-collector-contrib:0.165.0` | amd64, arm64 |
| caddy | `caddy:2.11.9-alpine` | amd64, arm64 |
| squid | `ubuntu/squid:7.2-26.04_edge` (only edge/beta tags seen; `6.6-24.04_edge`); no stable-tagged builds seen -> consider building from Debian apt `squid`. Maintained community alternative to tinyproxy: `vimagick/tinyproxy` is amd64-only, last pushed 2021: DO NOT USE | amd64, arm64 |
| pgvector | `pgvector/pgvector:0.8.7-pg18-trixie` | amd64, arm64 |
| ollama | `ollama/ollama:0.40.17` | amd64, arm64 |
| phoenix | `arizephoenix/phoenix:version-22.0.1-nonroot` | amd64, arm64 |
Digest pinning (`@sha256:`) not done; recommend adding in CI.

## 14. URL/domain/ML libs (checked 2026-11-22)
- `tldextract` **5.4.0** (Python >=3.10): `tldextract.TLDExtract(include_psl_private_domains=True, suffix_list_urls=())` -> bundled snapshot, no network (set `TLDEXTRACT_CACHE` for cache dir). Result has `.is_private`. `publicsuffix2` last release 2.20191221: STALE, do not use.
- UTS#39 skeleton: `confusable-homoglyphs` **3.3.1** provides `confusables.is_confusable(s, greedy=True)`, `is_dangerous(s)`, `is_mixed_script(s)` only; there is NO skeleton() function, and `is_dangerous("paypaI.com")` returned False (single-script lookalikes, e.g. capital I vs l, are not caught). Needs your own skeleton: load Unicode `confusables.txt` (UTS#39) mapping + NFKC + lowercase + strip; or evaluate PyPI `confusables` 1.2.0 (API UNVERIFIED).
- RDAP: `whoisit` **4.1.0** (Python >=3.10): `whoisit.bootstrap()` once (downloads IANA bootstrap; `save_bootstrap_data/load_bootstrap_data` for caching), `whoisit.domain("example.com") -> dict` (kwargs `raw, include_raw, allow_insecure_ssl, session, follow_related`), plus `domain_async`, `ip`, `asn`. Pulls `requests` and `httpx`. Return key layout: UNVERIFIED (not executed; needs network). Many ccTLDs (incl. .ae?) lack RDAP: UNVERIFIED -> keep a WHOIS fallback.
- `lightgbm` **4.7.0**; `scikit-learn` **1.9.1** (Python >=3.11) has `HistGradientBoostingClassifier` (native NaN + categorical support, no extra native dep). For tabular URL features at modest data size, HistGradientBoosting is adequate and avoids the libgomp/OpenMP wheel concerns in slim images; pick LightGBM only if you need speed on large data or monotone/ranking objectives (judgement, not doc-verified).

## 15. Threat feeds and UAE reporting (checked 2026-11-22)
- **OpenPhish Community**: free text feed `https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt`, refreshed every 12 hours, marked "Limited" (https://openphish.com/phishing_feeds.html). "By using the Community Feed, you accept the Terms of Use." General Terms (https://openphish.com/terms.html) say: not to use the Services for any commercial purposes; Services solely for personal use (research use allowed: academic, independent, personal); no redistribution/disclosure of information to third parties; "access the Services only using the interface and instructions that OpenPhish provides." No explicit rule on automated download, attribution, or rate limit. The terms page did not mention "Community Feed" by name. Academic program: non-commercial, attribution required, 60-day access (https://openphish.com/academic_use.html). Conclusion: a commercial product should NOT ingest it without a licence from OpenPhish; non-commercial/personal automated pull of the published feed.txt is not expressly forbidden but redistribution is. Needs legal confirmation.
- **PhishTank** (https://phishtank.org/developer_info.php): feeds `https://data.phishtank.com/data/online-valid.json.bz2` (also with `<app_key>` in the path), updated hourly; without key "a few downloads per day"; use descriptive User-Agent `phishtank/<username>`; HEAD requests with key are unlimited. Terms: Cisco EULA (not read). Whether new API key registration is currently open: UNVERIFIED (page links api_register.php only).
- **URLhaus** (https://urlhaus.abuse.ch/api/): YES an `Auth-Key` is required for the API and downloads; key goes in the URL path for exports (`https://urlhaus-api.abuse.ch/v2/files/exports/<KEY>/recent.csv`) and in the JSON body for submissions. No numeric rate limits; dumps not more often than every 5 min; free under fair use, commercial use may need paid subscription; CC0 not stated on that page (UNVERIFIED; see https://abuse.ch/terms-of-use/).
- **Abu Dhabi Police** official site https://www.adpolice.gov.ae/en/ (fetched 2026-11-22) shows: "Aman Service" with button "SUBMIT AMAN CASE" -> https://aman.adpolice.gov.ae ; two numbers under that heading: **8002626** and **2828** (page does not label which is which); "Complaints" -> https://cas.adpolice.gov.ae/ ; "Emergency Number" 999; "Need Immediate Assistance" 8003333; a Police entry listed as 998 but linked tel:999. The page does NOT mention cybercrime/e-crime, SMS, email or an "Ecrime" platform. https://aman.adpolice.gov.ae returned only a "connection lost" shell (content UNVERIFIED). Secondary sources (news, not official; https://gulfnews.com/living-in-uae/safety-security/how-to-report-online-fraud-and-phone-scams-in-abu-dhabi-1.1644936083156): 8002626 toll-free, SMS 2828, aman@adpolice.gov.ae, Abu Dhabi Police app. Treat those as UNVERIFIED against the official site. "Ecrime platform" (national ecrime.ae): UNVERIFIED, not fetched.
