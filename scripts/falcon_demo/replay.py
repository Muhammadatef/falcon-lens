"""`make replay RATE=2/s DURATION=10m`: steady labelled checks plus a Sentinel planted campaign.

Everything is invented (.test domains, brand falcon_demo_bank) and every check and event carries
source=replay. The campaign comes from sentinel_core.fixtures (same generator the Sentinel tests use),
re-timed to "now" and re-keyed per run so the Sentinel treats the domains as new and an incident fires.

What it does (details):
    Builds a plan of invented checks at the given rate and, unless --no-campaign is used, a planted
    campaign of Redis events so the Sentinel opens an incident. Then it plays the plan in real time and
    prints progress. Ctrl-C stops it (exit 130).

When to use it:
    To make dashboards and the Sentinel incident view move during a demo or rehearsal.

How to run:
    make replay RATE=2/s DURATION=10m
    PYTHONPATH=scripts uv run python -m falcon_demo replay --rate 2/s --duration 10m [--no-campaign] [--seed 7]

Inputs:
    Options above; .env values FL_MCP_SERVICE_KEY (120/min) or FL_SANDBOX_API_KEY (30/min); the rate is paced to 80% of
    that key's limit so nothing is throttled (a note is printed when the rate is lowered),
    FL_DEMO_REDIS_URL, ports.

Outputs / side effects:
    Sends checks to the local API and adds events to the Redis stream `fl:events`. All of it is labelled
    source=replay, so alerts for it are routed to the null receiver. Nothing is written to disk.

Safety notes:
    Every domain is invented (.test) and nothing is sent to a real site.
"""

from __future__ import annotations

import copy
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sentinel_core.fixtures import generate  # noqa: E402  (corpus.py put services/sentinel on sys.path)

from .common import SOURCE, ApiClient, ApiError, EventSink, Sleep, Throttled, paced_rate, pick_key
from .corpus import make_ulid

CLASS_WEIGHTS = (("dangerous", 0.35), ("suspicious", 0.2), ("no_warning_signs", 0.45))
HOSTS = {
    "dangerous": ("falcon-demo-bank-secure-pay.test", "falcon-demo-bnak.test", "falcon-dem0-bank.test"),
    "suspicious": ("falcon-demo-bank-support.test", "falcondemobank-offers.test"),
    "no_warning_signs": ("falcon-demo-bank.test",),
}
PATHS = ("/", "/login", "/ar/", "/help", "/verify")
CAMPAIGN_START_FRACTION = 0.4  # the planted campaign begins 40% into the run
CAMPAIGN_SPAN_FRACTION = 0.25  # and unfolds over 25% of it (the original takes 38 min)


@dataclass(frozen=True)
class Call:
    """One planned action: a URL check or a Redis event, t seconds after the start, with the expected verdict."""

    t: float  # seconds after start
    kind: str  # url | event
    value: str = ""  # url for kind=url
    expect: str | None = None
    event: dict[str, Any] | None = field(default=None, compare=False)


def parse_rate(s: str) -> float:
    """'2/s' | '120/m' | '0.5' (per second)."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(?:/\s*([smh]))?\s*", s)
    if not m:
        raise ValueError(f"bad RATE {s!r}; use e.g. 2/s or 120/m")
    unit = {"s": 1, "m": 60, "h": 3600}[m.group(2) or "s"]
    rate = float(m.group(1)) / unit
    if rate <= 0:
        raise ValueError("RATE must be > 0")
    return rate


def parse_duration(s: str) -> float:
    """'90', '90s', '10m', '1h30m' -> seconds."""
    parts = re.findall(r"([0-9]+)\s*([smh]?)", s.strip())
    if not parts or "".join(a + b for a, b in parts).replace(" ", "") != s.strip().replace(" ", ""):
        raise ValueError(f"bad DURATION {s!r}; use e.g. 10m or 90s")
    total = sum(int(n) * {"": 1, "s": 1, "m": 60, "h": 3600}[u] for n, u in parts)
    if total <= 0:
        raise ValueError("DURATION must be > 0")
    return float(total)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def campaign_calls(start: datetime, duration_s: float, run_tag: str, seed: int = 7) -> list[Call]:
    """The planted campaign from sentinel_core.fixtures, compressed into the run window."""
    fx = generate(seed)
    ids = set(fx.labels["incidents"][0]["event_ids"])
    chosen = [e for e in fx.events if e["event_id"] in ids]
    t0 = datetime.fromisoformat(chosen[0]["occurred_at"].replace("Z", "+00:00"))
    orig_span = (datetime.fromisoformat(chosen[-1]["occurred_at"].replace("Z", "+00:00")) - t0).total_seconds() or 1.0
    scale = min(1.0, CAMPAIGN_SPAN_FRACTION * duration_s / orig_span)
    base = CAMPAIGN_START_FRACTION * duration_s
    calls: list[Call] = []
    for e in chosen:
        off = (datetime.fromisoformat(e["occurred_at"].replace("Z", "+00:00")) - t0).total_seconds()
        t = base + off * scale
        at = start + timedelta(seconds=t)
        ev = copy.deepcopy(e)
        ev["event_id"] = f"evt_{make_ulid(at, f'{run_tag}|{e["event_id"]}')}"
        ev["occurred_at"] = _iso(at)
        ev["source"] = SOURCE
        if ev.get("verdict_id"):
            ev["verdict_id"] = f"vd_{make_ulid(at, f'{run_tag}|{e["verdict_id"]}')}"
        p = ev["payload"]
        if "domain_defanged" in p:
            p["domain_defanged"] = _tag_domain(p["domain_defanged"], run_tag, "[.]")
            p["first_seen"] = _iso(at)
        if "registrable_domain" in p:
            p["registrable_domain"] = _tag_domain(p["registrable_domain"], run_tag, ".")
        calls.append(Call(t=t, kind="event", event=ev))
    return calls


def _tag_domain(d: str, tag: str, dot: str) -> str:
    head, _, tld = d.rpartition(dot)
    return f"{head}-{tag}{dot}{tld}"  # unique per run so the Sentinel sees brand-new domains


def build_plan(rate: float, duration_s: float, start: datetime, seed: int = 7, campaign: bool = True) -> list[Call]:
    """Plan steady background checks plus (optionally) the planted campaign for the given rate and length."""
    rng = random.Random(seed)
    n = round(rate * duration_s)
    classes = [c for c, _ in CLASS_WEIGHTS]
    weights = [w for _, w in CLASS_WEIGHTS]
    run_tag = format(int(start.timestamp()) % (36**4), "x").zfill(4)
    calls = []
    for i in range(n):
        cls = rng.choices(classes, weights)[0]
        host = rng.choice(HOSTS[cls])
        url = f"https://{host}{rng.choice(PATHS)}?r={run_tag}{i}"  # unique query: avoids the verdict cache
        calls.append(Call(t=i / rate, kind="url", value=url, expect=cls))
    if campaign:
        calls += campaign_calls(start, duration_s, run_tag, seed)
    return sorted(calls, key=lambda c: c.t)


@dataclass
class Stats:
    """Running counters of what the replay has sent so far."""

    checks: int = 0
    events: int = 0
    throttled: int = 0
    errors: int = 0
    by_class: Counter[str] = field(default_factory=Counter)

    def line(self) -> str:
        """One-line progress summary."""
        mix = " ".join(f"{k}={v}" for k, v in sorted(self.by_class.items()))
        return f"checks={self.checks} events={self.events} throttled={self.throttled} errors={self.errors} [{mix}]"


def run_plan(
    plan: list[Call],
    client: ApiClient | None,
    sink: EventSink | None,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Sleep = time.sleep,
    workers: int = 8,
    on_tick: Callable[[Stats], None] | None = None,
) -> Stats:
    """Play the plan in real time against the API and the event sink, reporting progress."""
    st = Stats()
    t0 = clock()
    last_report = 0.0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = []
        for c in plan:
            delay = c.t - (clock() - t0)
            if delay > 0:
                sleep(delay)
            if c.kind == "event" and c.event is not None:
                if sink is None:
                    st.errors += 1
                else:
                    try:
                        sink.xadd_event(c.event)
                        st.events += 1
                    except (ApiError, OSError):
                        st.errors += 1
            elif client is not None:
                futures.append((c, pool.submit(client.check_url, c.value)))
            for f_c, f in [x for x in futures if x[1].done()]:
                futures.remove((f_c, f))
                _collect(st, f_c, f.exception())
            if on_tick and c.t - last_report >= 5:
                last_report = c.t
                on_tick(st)
        for f_c, f in futures:
            _collect(st, f_c, f.exception())
    return st


def _collect(st: Stats, c: Call, exc: BaseException | None) -> None:
    if exc is None:
        st.checks += 1
        if c.expect:
            st.by_class[c.expect] += 1
    elif isinstance(exc, Throttled):
        st.throttled += 1
    else:
        st.errors += 1
        if not isinstance(exc, ApiError):
            raise exc


def main(argv: list[str]) -> int:
    """Parse options, warn about rate limits, build and run the plan; 130 on Ctrl-C."""
    import argparse

    from .common import Endpoints, default_sink, load_env

    ap = argparse.ArgumentParser(prog="replay")
    ap.add_argument("--rate", default="2/s")
    ap.add_argument("--duration", default="10m")
    ap.add_argument("--no-campaign", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    try:
        rate, dur = parse_rate(a.rate), parse_duration(a.duration)
    except ValueError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    env = load_env()
    api_key, key_limit = pick_key(env)
    paced = paced_rate(rate, key_limit)
    if paced < rate:
        print(
            f"note: {rate * 60:.0f} checks/min exceeds the key limit of {key_limit}/min; pacing to "
            f"{paced * 60:.0f}/min so no check is throttled. The planted campaign is unaffected.",
            file=sys.stderr,
        )
        rate = paced
    ep = Endpoints.from_env(env)
    client = ApiClient(ep.gateway, api_key)
    if not client.healthy():
        print(f"replay: API not reachable at {ep.gateway}. Start the stack first (make up).", file=sys.stderr)
        return 1
    sink: EventSink | None = None
    if not a.no_campaign:
        try:
            sink = default_sink(env)
        except Exception as exc:  # noqa: BLE001
            print(f"warn: event sink unavailable ({exc}); campaign stream skipped", file=sys.stderr)
    plan = build_plan(rate, dur, datetime.now(UTC), a.seed, campaign=sink is not None)
    n_url = sum(c.kind == "url" for c in plan)
    print(f"replay: {n_url} checks + {len(plan) - n_url} events over {dur:.0f}s, source=replay")
    try:
        st = run_plan(plan, client, sink, on_tick=lambda s: print("  " + s.line(), flush=True))
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    finally:
        if sink:
            sink.close()
        client.close()
    print("done: " + st.line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
