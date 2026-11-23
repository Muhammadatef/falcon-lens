"""`make seed`: push the corpus through the real API and worker with source=replay. Idempotent.

What it does:
    Builds the seed corpus (see corpus.py), submits each item to the running API at a gentle rate, and
    publishes hash-only phishing events to Redis. It remembers what it already sent in
    data/private/seed_state.json, so running it twice does not duplicate work.

When to use it:
    Once after `make up`, so the dashboards and the app are not empty. `make demo` calls it for you.

How to run:
    make seed                      (add FORCE=1 to resubmit everything)
    PYTHONPATH=scripts uv run python -m falcon_demo seed [--groups a,b] [--force] [--rate 0.4]
        [--legit-limit 60] [--phish-limit 50] [--wait 0]

Inputs:
    Options above, .env (ports, FL_SANDBOX_API_KEY, FL_DEMO_REDIS_URL) and the corpus files.

Outputs / side effects:
    HTTP checks to the local gateway, Redis stream `fl:events` entries, and the state file
    data/private/seed_state.json (gitignored). Prints a summary; exits 1 if any item failed or the API is
    not reachable. `make demo-reset` deletes the state file.

Safety notes:
    Only reserved/test domains and hashes are sent; the allow-list in corpus.py blocks everything else.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .common import PRIVATE_DIR, ApiClient, ApiError, EventSink, Sleep, Throttled, retry_throttled
from .corpus import Item, hash_event, item_allowed

STATE_PATH = PRIVATE_DIR / "seed_state.json"


@dataclass
class Summary:
    """Counters and messages collected while seeding; `render` prints them."""

    submitted: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    failed: Counter[str] = field(default_factory=Counter)
    blocked: Counter[str] = field(default_factory=Counter)
    verdicts: Counter[str] = field(default_factory=Counter)
    mismatches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        """The summary text printed at the end of a seed run."""
        lines = ["seed summary (source=replay)"]
        groups = sorted(set(self.submitted) | set(self.skipped) | set(self.failed))
        for g in groups:
            lines.append(
                f"  {g:<9} submitted={self.submitted[g]:<4} already-seeded={self.skipped[g]:<4} failed={self.failed[g]}"
            )
        if self.blocked:
            lines.append("  blocked by allowlist: " + ", ".join(f"{k}={v}" for k, v in sorted(self.blocked.items())))
        if self.verdicts:
            lines.append("  verdicts seen: " + ", ".join(f"{k}={v}" for k, v in sorted(self.verdicts.items())))
        if self.mismatches:
            lines.append(
                f"  {len(self.mismatches)} verdict(s) differ from the expected label (first: {self.mismatches[0]})"
            )
        for e in self.errors[:3]:
            lines.append(f"  error: {e}")
        return "\n".join(lines)


def load_state(path: Path = STATE_PATH) -> dict[str, str]:
    """Read the record of already-seeded items from data/private/seed_state.json."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def save_state(state: dict[str, str], path: Path = STATE_PATH) -> None:
    """Write the record of already-seeded items."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, sort_keys=True))


def progress_bar(done: int, total: int, width: int = 30) -> str:
    """Text progress bar such as [####....] 12/40."""
    n = total or 1
    fill = int(width * done / n)
    return f"[{'#' * fill}{'.' * (width - fill)}] {done}/{total}"


def run_seed(
    items: list[Item],
    client: ApiClient | None,
    sink: EventSink | None,
    *,
    state: dict[str, str],
    force: bool = False,
    rate_per_s: float = 0.4,
    wait: float = 0,
    sleep: Sleep = time.sleep,
    on_progress: Callable[[int, int], None] | None = None,
    save: Callable[[dict[str, str]], None] | None = None,
) -> Summary:
    """Submit every item once. `state` maps Item.key -> verdict_id (or 'event'); present keys are skipped."""
    s = Summary()
    gap = 1.0 / rate_per_s if rate_per_s > 0 else 0.0
    for n, item in enumerate(items, 1):
        if on_progress:
            on_progress(n - 1, len(items))
        if not item_allowed(item):  # defence in depth: nothing off the allowlist reaches the API
            s.blocked[item.group] += 1
            continue
        if not force and item.key in state:
            s.skipped[item.group] += 1
            continue
        try:
            if item.kind == "event":
                if sink is None:
                    raise ApiError("no Redis sink (is the stack up?)")
                sink.xadd_event(hash_event(item))
                state[item.key] = "event"
            else:
                if client is None:
                    raise ApiError("no API client")
                c = client
                doc = _submit(c, item, wait, sleep)
                state[item.key] = str(doc.get("verdict_id", "submitted"))
                v = doc.get("verdict")
                if isinstance(v, str):
                    s.verdicts[v] += 1
                    if item.expect and v != item.expect:
                        s.mismatches.append(f"{item.group}:{item.key} expected {item.expect} got {v}")
            s.submitted[item.group] += 1
            if gap and item.kind != "event":
                sleep(gap)
        except Throttled as exc:
            s.failed[item.group] += 1
            s.errors.append(f"{exc}; raise FL_RATE_LIMIT_PER_IP_PER_MIN in .env for demos")
        except ApiError as exc:
            s.failed[item.group] += 1
            s.errors.append(str(exc))
            if "unreachable" in str(exc) or "redis-cli" in str(exc):
                break  # the stack is down; stop instead of failing every item
        if save and n % 10 == 0:
            save(state)
    if save:
        save(state)
    if on_progress:
        on_progress(len(items), len(items))
    return s


def _submit(client: ApiClient, item: Item, wait: float, sleep: Sleep) -> dict[str, Any]:
    idem = f"seed-{item.key}"
    if item.kind == "url":
        return retry_throttled(lambda: client.check_url(item.value, idem, wait), sleep)
    return retry_throttled(lambda: client.check_message(item.value, idem, wait), sleep)


def main(argv: list[str]) -> int:
    """Parse options, build the corpus and seed it; 1 if the API is down or an item failed."""
    import argparse

    from .common import Endpoints, default_sink, load_env
    from .corpus import GROUPS, build_corpus

    ap = argparse.ArgumentParser(prog="seed")
    ap.add_argument("--groups", default=",".join(GROUPS))
    ap.add_argument("--force", action="store_true", help="resubmit items already seeded")
    ap.add_argument("--rate", type=float, default=0.4, help="submissions per second (API limit is per IP per minute)")
    ap.add_argument("--legit-limit", type=int, default=60)
    ap.add_argument("--phish-limit", type=int, default=50)
    ap.add_argument("--wait", type=float, default=0, help="seconds to wait for each verdict (max 8)")
    a = ap.parse_args(argv)

    env = load_env()
    groups = tuple(g for g in a.groups.split(",") if g)
    items, counts, skipped = build_corpus(groups, a.legit_limit, a.phish_limit)
    for g, n in skipped.items():
        if n:
            print(f"note: {n} '{g}' item(s) skipped by the reserved-domain allowlist")
    for g, n in counts.items():
        if n == 0 and not skipped.get(g):
            print(f"note: no '{g}' items found (source file not present yet); skipping that group")
    ep = Endpoints.from_env(env)
    client = ApiClient(ep.gateway, env.get("FL_SANDBOX_API_KEY"))
    if not client.healthy():
        print(f"seed: API not reachable at {ep.gateway}. Start the stack first (make up).", file=sys.stderr)
        return 1
    sink: EventSink | None = None
    if any(i.kind == "event" for i in items):
        try:
            sink = default_sink(env)
        except Exception as exc:  # noqa: BLE001 - degrade: seed the checks even without the event bus
            print(f"warn: event sink unavailable ({exc}); phishing hash events skipped", file=sys.stderr)
    state = load_state()

    def bar(done: int, total: int) -> None:
        print("\r" + progress_bar(done, total), end="", flush=True)

    summary = run_seed(
        items,
        client,
        sink,
        state=state,
        force=a.force,
        rate_per_s=a.rate,
        wait=a.wait,
        on_progress=bar,
        save=save_state,
    )
    print()
    print(summary.render())
    if sink:
        sink.close()
    client.close()
    return 1 if sum(summary.failed.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
