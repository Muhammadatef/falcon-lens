#!/usr/bin/env python3
"""Defensive-only guard (CLAUDE.md): the public repo must not carry live URLs or private data.

Fails (exit 1) when
  * any tracked file lives under data/private/ (gitignored, must never be committed), or
  * a tracked file under data/, evals/, config/ or any tests/fixtures directory contains a
    non-defanged http(s) URL whose host is not allowlisted (docs, official domains, reserved
    test domains) and the line is not a `source_url:` provenance entry.

Defanged forms (hxxp://, example[.]com) never match. Run from the repo root.

What it does:
    Lists every file git tracks (`git ls-files`) and fails if one sits under data/private/, or if a file
    under data/, evals/, config/ or a tests/fixtures folder holds a normal http(s) URL to a host that is not
    on the built-in allow-list. Lines starting with `source_url:` are skipped. It only reads files.

When to use it:
    Before every commit or PR, and in CI. It protects the "defensive only" rule: no live phishing links.

How to run:
    make guard                          (same as: python3 scripts/check_no_live_urls.py)
    Run it from the repo root; it needs `git` and nothing else (standard library only).

Inputs:
    No arguments or env vars. Reads the tracked files of the current git checkout.

Outputs / side effects:
    Prints "check_no_live_urls: ok" and exits 0, or prints one `path:line: ...` per problem to stderr and
    exits 1. Writes nothing and makes no network calls.

Safety notes:
    To fix a failure, write the URL defanged (hxxp://, example[.]com) instead of adding the host to the
    allow-list. Never commit anything under data/private/.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

SCAN_DIRS = ("data/", "evals/", "config/")
SCAN_PARTS = ("tests", "fixtures", "test", "__fixtures__")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".lock", ".whl", ".gz", ".zip"}
SKIP_NAMES = {"pnpm-lock.yaml", "uv.lock"}

ALLOWED_HOSTS = {
    "localhost",
    "127.0.0.1",
    "falcon-lens.local",
    "github.com",
    "raw.githubusercontent.com",
    "json-schema.org",
    "openphish.com",
    "phishtank.org",
    "data.phishtank.com",
    "urlhaus.abuse.ch",
    "urlhaus-api.abuse.ch",
    "abuse.ch",
    "platform.claude.com",
    "docs.anthropic.com",
    "code.claude.com",
    "docs.ollama.com",
    "ollama.com",
    "falconlens.app",
    "dns.google",  # Google public DNS-over-HTTPS (hosting/ASN enrichment, evidence pack)
    "rdap.org",  # RDAP bootstrap redirector (registrar/abuse contact)  # our own public demo domain (owner-registered, 24 Nov)
}
ALLOWED_SUFFIXES = (
    ".test",
    ".invalid",
    ".example",
    ".local",
    ".localhost",
    "example.com",
    "example.org",
    "example.net",
    ".adpolice.gov.ae",
)
URL_RE = re.compile(r"https?://[^\s\"'<>)\]}\\,]+", re.IGNORECASE)


def host_of(url: str) -> str:
    """Return the lower-case host of a URL (empty string if it cannot be parsed)."""
    try:
        return urlsplit(url).hostname or ""
    except ValueError:  # malformed (e.g. bad IPv6 literal): treat as unknown host, i.e. flagged
        return "<unparseable>"


# Reviewed synthetic inputs used by unit tests (obfuscation / lookalike / shared-hosting cases).
# They are strings fed to pure functions and are never fetched. Add new entries deliberately.
REVIEWED_TEST_HOSTS = (
    ".github.io",
    ".ngrok-free.app",
    ".trycloudflare.com",
    "wikipedia.org",
    ".example.co.uk",
    "adpolicr.com",
    "adpolice.com",
    "dubaipolice-gov.ae",
    "verify-fine.xyz",
    # T-008 domain/reputation tests: public service endpoints (mocked, never fetched) and invented hosts
    "crt.sh",
    "data.iana.org",
    "safebrowsing.googleapis.com",
    "falcon-demo-shop.com",
    "falcon-demo-shop.ae",
)
INTERNAL_SUFFIXES = (".internal", ".arpa", ".docker.internal")


def allowed(host: str) -> bool:
    """True if the host is on the allow-list (docs, official domains, reserved test domains)."""
    host = host.lower().rstrip(".")
    if not host or "<" in host or "{" in host or "%" in host or not host.isascii():
        return True  # templated / malformed / non-ASCII test input, not a fetchable host
    if "." not in host or host.endswith(INTERNAL_SUFFIXES):
        return True  # single-label or internal service name (SSRF test inputs)
    if set(host) <= set("0123456789abcdefx."):
        return True  # numeric IP obfuscation forms (octal/hex/short), SSRF test inputs
    try:
        ipaddress.ip_address(host)
        return True  # literal IPs are SSRF test inputs
    except ValueError:
        pass
    if any(host == h.lstrip(".") or host.endswith(h) for h in REVIEWED_TEST_HOSTS):
        return True
    if host in ALLOWED_HOSTS or host == "adpolice.gov.ae":
        return True
    return host.endswith(ALLOWED_SUFFIXES)


def tracked_files() -> list[str]:
    """Every file git tracks, as repo-relative paths."""
    out = subprocess.run(["git", "ls-files"], check=True, capture_output=True, text=True)  # noqa: S607
    return out.stdout.splitlines()


def in_scope(path: str) -> bool:
    """True for files this guard scans (data/, evals/, config/ and tests/fixtures folders)."""
    return path.startswith(SCAN_DIRS) or any(part in SCAN_PARTS for part in Path(path).parts[:-1])


def main() -> int:
    """Run the guard; return 0 if clean, 1 if any problem was found."""
    problems: list[str] = []
    for path in tracked_files():
        if path.startswith("data/private/"):
            problems.append(f"{path}: data/private must never be committed")
            continue
        p = Path(path)
        if not in_scope(path) or p.suffix.lower() in SKIP_SUFFIXES or p.name in SKIP_NAMES:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("source_url:"):
                continue
            for match in URL_RE.finditer(line):
                host = host_of(match.group(0))
                if not allowed(host):
                    problems.append(f"{path}:{lineno}: non-defanged URL to {host!r} (use hxxp / [.])")
    if problems:
        print("check_no_live_urls: FAILED", file=sys.stderr)
        print("\n".join(problems), file=sys.stderr)
        return 1
    print("check_no_live_urls: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
