# PR-4 review: T-003 SSRF guard + guarded HTTP client (library)

- Former PR #4 · local branch `keep/feat/security-ssrf-egress` · head `9762f05`
- Task: T-003 (builder-security, P0) · round 1 of 2 · reviewer: supervisor (L2) · 2026-11-22
- The GitHub repo is being recreated, so this was reviewed from the local branch only. No `gh` posting.

## Verdict: **CHANGES REQUESTED**

The guard itself held up against every bypass I tried: IPv6 embedded-IPv4 forms, NAT64 and 6to4 metadata, obfuscated numerics, IDN and full-width dots, userinfo tricks, rebinding on a redirect hop, and redirects to internal targets. All 151 tests pass and mypy --strict is clean. Two defects block the merge. Both fail closed, but one breaks the documented fixture integration and the other breaks the client's exception contract on attacker input.

## Checks run (worktree `scratchpad/fl-review-4`, detached at `9762f05`)

| Command | Result |
|---|---|
| `PYTHONPATH=packages/falcon_core/src uv run --no-project --with pytest --with pytest-asyncio --with httpx --with dnspython pytest packages/falcon_core/tests/security -q` | exit 0, `151 passed, 1 skipped in 0.35s` (the live test is opt-in) |
| same command **without** `--with dnspython` | `151 passed, 1 skipped`. dnspython isn't used (see finding 5) |
| `uvx ruff check --isolated <security src+tests>` | exit 1, 2× `I001` (`tests/security/test_http.py:3`, `test_ssrf.py:7`). This only happens because there's no `known-first-party` config yet |
| same plus `--config 'lint.isort.known-first-party=["falcon_core"]'` | exit 0, `All checks passed!` |
| `uvx ruff format --isolated --check <same>` | exit 0, `5 files already formatted` |
| `cd packages/falcon_core && MYPYPATH=src uv run --no-project --with mypy --with httpx --with pytest --with pytest-asyncio mypy --strict --explicit-package-bases src/falcon_core/security tests/security` | exit 0, `Success: no issues found in 5 source files` (without `MYPYPATH`/`--explicit-package-bases` the namespace package isn't found, so T-001 must set this) |
| `gitleaks git . --no-banner` | exit 0, no leaks |
| `git merge-tree --write-tree main keep/feat/security-ssrf-egress` | **exit 1**, `CONFLICT (content): Merge conflict in DECISIONS.md` |
| URL/defang grep on the diff | only doc URLs and reserved or test hosts. No phishing URLs |
| Bypass probe `scratchpad/probes/pr4_probe.py` (66 URL forms, 10 CONNECT hosts, redirect and rebinding cases, `python -I`) | see below |

### Bypass probe results
- **Blocked, with the right reason**: `[::ffff:127.0.0.1]`, `[::ffff:7f00:1]`, `[0:0:0:0:0:ffff:127.0.0.1]`, `[::127.0.0.1]`, `[2002:7f00:1::]` (6to4 loopback), `[2002:a9fe:a9fe::]` and `[64:ff9b::a9fe:a9fe]` (metadata through 6to4 and NAT64), `[::ffff:a9fe:a9fe]`, `[::ffff:0:7f00:1]` (IPv4-translated → reserved), `[::]`, `[0::1]`, `[fe80::1%25eth0]`, `[2001:0::1]`, `[64:ff9b:1::1]`, `[100::1]`, upper-case `FD00:EC2::254`. Also `0`, `0.0.0.0`, `127.0.0.1.`, `127.000.000.001`, `017700000001`, `0x7f.0x0.0x0.0x1`, `127.0.1`, `1.1.1.1.1`, full-width `１２７.０.０.１`, `127。0。0。1` and `127．0．0．1` (IDNA-mapped, then loopback), `①②⑦.0.0.1`, `localhost.`, `foo.localhost`, `metadata.google.internal`, `instance-data`, `kubernetes.default.svc`, `%40` and `%2540` userinfo, port `8080`, backslash and whitespace forms, ZWSP host.
- **DNS rebinding**: the resolver returns a public IP for the first hop and `127.0.0.1` on the redirect hop. Result: blocked `loopback`, and the wire saw only `http://93.184.215.14/` with `Host: rebind.example.org`, so pinning works.
- **Redirect chains**: Location values `http://[::ffff:169.254.169.254]/`, `http://[64:ff9b::a9fe:a9fe]/`, `\\127.0.0.1/`, `/\127.0.0.1/`, `//0x7f.1/`, `//[::1]/x`, userinfo and `gopher:` were all blocked before any second request.
- `evil.com#@127.0.0.1` → host `evil.com`, which matches WHATWG and httpx (no parser differential).

## Findings

### Blocking
1. **MEDIUM: `GuardPolicy.allow_hosts` doesn't work through the real transport, so the documented T-009 fixture path fails.** `resolve_and_check` (`ssrf.py:492-493`) skips IP checks for allow-listed hosts. But `PinnedNetworkBackend.connect_tcp` (`http.py:188-190`) re-checks the IP with `ip_block_reason` and knows nothing about `allow_hosts`. Probe: `safe_fetch("http://falcon-demo-bank.test/", resolver=→["172.18.0.5"], policy=GuardPolicy(allow_hosts={"falcon-demo-bank.test"}))` → `SSRFBlocked private`. The PR body ("The worker or proxy for the internal fixture network must pass `GuardPolicy(allow_hosts=…)`") and DECISIONS line "The `falcon-demo-bank.test` fixture needs an explicit `GuardPolicy(allow_hosts=...)`" describe a path that cannot work in direct mode. `test_allow_hosts_is_explicit_opt_in` (`test_ssrf.py:171`) only tests the syntactic layer.
   *Fix (choose one):* (a) carry the exact IPs resolved for an allow-listed host to the backend for that one connection (for example a per-request allowed-IP set passed through a `contextvars.ContextVar`, never a policy-wide CIDR), and add a test through `_build_transport` (not MockTransport) that an allow-listed host on a private IP connects while a non-listed host on the same IP is refused; or (b) remove `allow_hosts` from direct mode, state that fixture traffic only goes via the egress proxy, and fix the PR body and DECISIONS line to match. Either way, production stays empty.
2. **LOW-MEDIUM: a malformed `Location` raises a raw `httpx.InvalidURL` out of `fetch()`.** httpx builds `response.next_request` even with `follow_redirects=False`. For `Location: http:127.0.0.1/` (also `http:evil.org`, `https:foo`), `self._client.send` (`http.py:491`) raises `httpx.InvalidURL` from `httpx/_client.py:_send_handling_redirects`. `InvalidURL` isn't an `httpx.HTTPError`, so the handlers at `http.py:411-425` miss it. The documented contract is "raises SSRFBlocked or FetchFailed". Any attacker server can trigger this, and the response stream isn't closed. It fails closed, but a caller that catches only the documented types crashes.
   *Fix:* catch `httpx.InvalidURL` in `_send`/`fetch` and map it to `SSRFBlocked(INVALID_URL, "bad Location")`, the same as `http.py:449-452`. Add a test with MockTransport for these three Location values.

### Non-blocking
3. **LOW** `ssrf.py:210-211`: IPv4-compatible `::a.b.c.d` with a *public* inner address is allowed (`[::8.8.8.8]` → ALLOW). `::/96` isn't routable, so connects just fail, but unwrapping should only ever make a decision stricter. Block `::/96` (except `::`/`::1`, which are already handled) as `reserved` after judging the inner address.
4. **LOW** `http.py:403-404`: `max_bytes` and `max_redirects` are clamped, but `timeout` isn't. A caller can pass `timeout=600`. Clamp it to `DEFAULT_TIMEOUT_S`, matching "callers can lower the caps but never raise them".
5. **LOW**: the PR's test command includes `--with dnspython`, but no code uses it, and DECISIONS says "No dnspython". Drop it from the command.
6. **Proxy-mode caveat** (accepted as designed, carried to the egress card). In proxy mode the client pre-checks with its own resolution, and then the proxy resolves again, so the TOCTOU window is closed only if the proxy pins. The egress PR must ship these acceptance tests: (a) CONNECT to a name that resolves public on the client and private at the proxy → 403; (b) the proxy dials the checked IP, never the name; (c) absolute-form plain-HTTP requests run through `validate_url` + `resolve_and_check`; (d) the sandbox Chromium can't reach anything except through the proxy (network test). Until then, `GuardedHTTPClient(proxy=…)` must not be used in production.
7. `_build_transport` swaps the private `_pool`. This is accepted given the pinning test. Pin `httpx>=0.28.1,<0.29` in T-001.

### Merge
8. Rebase on `main` (`f8e79c4`). `DECISIONS.md` conflicts. While rebasing, fix the `allow_hosts` DECISIONS line to match finding 1.

## Eval impact
None directly. `validate_url` accepts all 411 rows of the PR-8 legit set (`scratchpad/probes/pr4_legit.py`: `blocked: []`; syntactic layer only, no DNS). Once ctx.http is wired, block reasons flow to `fl_ssrf_blocked_total{reason}` (T-014).
