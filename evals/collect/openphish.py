# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "tldextract"]
# ///
"""Poll the OpenPhish community feed (research use, no redistribution).

Feed: https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt
Published update interval: 12 hours (openphish.com/phishing_feeds.html, checked 2026-11-22).
Raw rows go ONLY under data/private/ (gitignored). The sole public output is
evals/manifests/phishing.manifest.jsonl, hash-only (OpenPhish bars redistribution).
Data dir: env FL_DATA_DIR (the `data` dir), default main checkout's data/.
`--rebuild-manifest` regenerates the manifest from raw rows without polling.

Run: uv run --no-project --with httpx --with tldextract python evals/collect/openphish.py
Exit codes: 0 ok, 3 refused by rate guard, 4 corrupt state.json, 1 fetch error.

What it does (summary):
    Downloads the public feed, removes URLs it has seen before, saves the raw rows privately, and appends
    hash-only rows to the public manifest. A rate guard refuses to poll more than once per 12 hours.

When to use it:
    To grow the phishing eval set over time (the temporal split needs several polls). Normally run by
    scripts/collect_loop.sh rather than by hand.

How to run:
    uv run --no-project --with httpx --with tldextract python evals/collect/openphish.py
    ... evals/collect/openphish.py --rebuild-manifest     (no network; rebuild the manifest from raw rows)

Inputs:
    Env FL_DATA_DIR (optional), the OpenPhish feed over HTTPS, and state.json in the private feed folder.

Outputs / side effects:
    Appends to data/private/feeds/openphish/<date>.jsonl, state.json and snapshot_queue.jsonl (all
    gitignored, they hold real URLs), and to evals/manifests/phishing.manifest.jsonl (hashes only,
    committed). Prints new_rows=N.

Safety notes:
    Never print, paste or commit the raw rows; OpenPhish forbids redistribution. Never open the URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

FEED_URL = "https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt"
TERMS_URL = "https://openphish.com/terms.html"
POLL_INTERVAL = timedelta(hours=12)

ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    """FL_DATA_DIR (the `data` dir) or the MAIN checkout's data dir, so worktrees share data/private."""
    env = os.environ.get("FL_DATA_DIR")
    if env:
        return Path(env)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return Path(out).parent / "data"
    except (OSError, subprocess.CalledProcessError):
        return ROOT / "data"


FEED_DIR = data_dir() / "private" / "feeds" / "openphish"
MANIFEST = ROOT / "evals" / "manifests" / "phishing.manifest.jsonl"
QUEUE = FEED_DIR / "snapshot_queue.jsonl"


MAX_FEED_BYTES = 5 * 1024 * 1024


class PollTooEarly(Exception):
    """Raised when a poll would occur inside the published update interval."""


class CorruptState(Exception):
    """state.json exists but is unreadable; refuse to poll until a human fixes it."""


class FeedTooLarge(Exception):
    """Feed response exceeded MAX_FEED_BYTES."""


def sha256(s: str) -> str:
    """Hex SHA-256 of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def canonicalize(url: str) -> str | None:
    """Lowercase scheme+host, drop fragment and default port; None if not http(s)."""
    try:
        p = urlsplit(url.strip())
        host = p.hostname
        port = p.port
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not host:
        return None
    netloc = host.lower()
    if port and port not in (80, 443):
        netloc += f":{port}"
    return urlunsplit((p.scheme.lower(), netloc, p.path or "/", p.query, ""))


_extractor = None


def registrable_domain(url: str) -> str:
    """eTLD+1 using the bundled PSL snapshot incl. private domains (no network)."""
    global _extractor
    import tldextract

    if _extractor is None:
        _extractor = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
    host = urlsplit(url).hostname or ""
    ext = _extractor(host)
    return ext.top_domain_under_public_suffix or host


def manifest_row(canon: str, first_seen: str) -> dict[str, object]:
    """Hash-only public row: nothing from which the URL can be reconstructed."""
    return {
        "url_sha256": sha256(canon),
        "registrable_domain_sha256": sha256(registrable_domain(canon)),
        "first_seen": first_seen,
        "feed": "openphish_community",
    }


def rebuild_manifest(feed_dir: Path, manifest: Path) -> int:
    """Regenerate the manifest from raw rows (no network)."""
    rows = []
    for f in sorted(feed_dir.glob("2*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                rows.append(manifest_row(r["url"], r["first_seen"]))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


def check_rate_guard(state_path: Path, now: datetime, interval: timedelta = POLL_INTERVAL) -> None:
    """Raise PollTooEarly if the last poll was inside the 12-hour interval."""
    if not state_path.exists():
        return
    try:
        last = datetime.fromisoformat(json.loads(state_path.read_text())["last_poll_utc"])
    except (ValueError, KeyError, TypeError) as e:
        raise CorruptState(f"corrupt {state_path.name}: fix or delete it manually") from e
    if now - last < interval:
        wait = int((last + interval - now).total_seconds())
        raise PollTooEarly(f"refusing poll: next allowed in {wait}s")


def known_hashes(feed_dir: Path) -> set[str]:
    """Hashes of every URL already stored, so repeats are skipped."""
    seen: set[str] = set()
    for f in feed_dir.glob("2*.jsonl"):
        for line in f.read_text().splitlines():
            if line.strip():
                seen.add(json.loads(line)["sha256"])
    return seen


def process_feed(text: str, now: datetime, feed_dir: Path, manifest: Path, queue: Path | None = None) -> int:
    """Dedup against history, append raw rows (private) and manifest rows (public)."""
    feed_dir.mkdir(parents=True, exist_ok=True)
    state_path = feed_dir / "state.json"
    feed_age = None  # seconds since previous poll: upper bound on entry age (feed has no timestamps)
    if state_path.exists():
        prev = datetime.fromisoformat(json.loads(state_path.read_text())["last_poll_utc"])
        feed_age = int((now - prev).total_seconds())
    seen = known_hashes(feed_dir)
    ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_rows: list[dict[str, object]] = []
    man_rows: list[dict[str, object]] = []
    for line in text.splitlines():
        canon = canonicalize(line)
        if canon is None:
            continue
        h = sha256(canon)
        if h in seen:
            continue
        seen.add(h)
        raw_rows.append({"url": canon, "first_seen": ts, "feed_age": feed_age, "sha256": h})
        man_rows.append(manifest_row(canon, ts))
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with (feed_dir / f"{now:%Y%m%d}.jsonl").open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in raw_rows)
    with manifest.open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in man_rows)
    if queue is not None:  # consumed by snapshot_queue.py (blocked on T-004)
        with queue.open("a") as f:
            f.writelines(json.dumps({"url": r["url"], "sha256": r["sha256"]}) + "\n" for r in raw_rows)
    state_path.write_text(json.dumps({"last_poll_utc": now.isoformat(), "new_rows": len(raw_rows)}))
    return len(raw_rows)


def poll(now: datetime | None = None) -> int:
    """Download the feed (size-capped) and store the new rows; returns how many were new."""
    import httpx

    now = now or datetime.now(UTC)
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    check_rate_guard(FEED_DIR / "state.json", now)
    chunks: list[bytes] = []
    size = 0
    with httpx.stream("GET", FEED_URL, timeout=30, headers={"User-Agent": "research-feed-poller/1.0"}) as r:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            size += len(chunk)
            if size > MAX_FEED_BYTES:
                raise FeedTooLarge(f"feed exceeds {MAX_FEED_BYTES} bytes")
            chunks.append(chunk)
    text = b"".join(chunks).decode("utf-8", errors="replace")
    return process_feed(text, now, FEED_DIR, MANIFEST, QUEUE)


def main() -> int:
    """Poll the feed, or with --rebuild-manifest rebuild the manifest; exit codes in the module docstring."""
    if "--rebuild-manifest" in sys.argv:
        print(f"manifest_rows={rebuild_manifest(FEED_DIR, MANIFEST)}")
        return 0
    try:
        n = poll()
    except PollTooEarly as e:
        print(e, file=sys.stderr)
        return 3
    except CorruptState as e:
        print(e, file=sys.stderr)
        return 4
    except Exception as e:  # noqa: BLE001
        print(f"fetch failed: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"new_rows={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
