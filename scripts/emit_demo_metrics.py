#!/usr/bin/env python3
"""Emit SYNTHETIC fl_ metrics (source=replay) so the Grafana dashboards can be eyeballed
before the real pipeline exists. Nothing here is a detection result: the values are random.

Usage:  uv run python scripts/emit_demo_metrics.py [--port 9199] [--seconds 0]

It serves /metrics on 0.0.0.0:<port> from the real metric registry (so names/labels are the
contract's) and writes infra/prometheus/demo/targets.yml so Prometheus (file_sd, refreshed
automatically) scrapes it at host.docker.internal:<port>. The file is removed on exit.
"""

from __future__ import annotations

import argparse
import contextlib
import random
import time
from pathlib import Path

from prometheus_client import start_http_server

from falcon_core.telemetry import metrics as m

TARGETS = Path(__file__).resolve().parents[1] / "infra" / "prometheus" / "demo" / "targets.yml"
VERDICTS = ["dangerous", "suspicious", "no_warning_signs"]
TIERS = ["t0", "t1", "t2", "t3"]
STAGES = ["t0", "t1", "t2", "t3", "arbiter", "sandbox", "total"]
BRANDS = ["falcon_demo_bank"]  # the only invented brand allowed in fixtures
FEEDS = ["openphish", "urlhaus"]


def tick(rng: random.Random, state: dict[str, float]) -> None:
    for _ in range(rng.randint(2, 7)):
        verdict = rng.choices(VERDICTS, weights=[3, 2, 6])[0]
        tier = rng.choices(TIERS, weights=[6, 3, 2, 1])[0]
        m.record_verdict(
            input_type=rng.choice(["url", "message", "email"]),
            verdict=verdict,
            tier=tier,
            route=rng.choice(["cascade", "llm_only"]),
            source="replay",
            degraded=rng.random() < 0.02,
        )
        base = {"t0": 0.03, "t1": 0.3, "t2": 1.5, "t3": 4.0}[tier]
        total = 0.0
        for stage in ("t0", "t1", "t2", "t3", "arbiter", "sandbox"):
            if stage == "arbiter" or stage <= tier or (stage == "sandbox" and tier in ("t2", "t3")):
                d = rng.lognormvariate(0, 0.6) * (0.02 if stage == "arbiter" else base)
                m.STAGE_LATENCY.labels(stage).observe(d)
                total += d
        m.STAGE_LATENCY.labels("total").observe(total)
        if tier != "t0":
            m.ESCALATIONS.labels("t0", tier).inc()
        m.CACHE_HITS.labels(rng.choice(["redis", "verdict"])).inc(rng.random() < 0.5)
        if tier == "t3":
            model = rng.choice(["claude-haiku-5-5", "claude-sonnet-5-5"])
            tin, tout = rng.randint(800, 2500), rng.randint(100, 500)
            m.record_llm(
                model=model,
                role="judge",
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=tin * 1e-7 + tout * 5e-7,
                fallback=rng.random() < 0.03,
            )
            m.AGENT_STEPS.observe(rng.randint(2, 8))
    if rng.random() < 0.1:
        m.TOOL_ERRORS.labels(rng.choice(["whois", "tls", "dns"]), "timeout").inc()
    if rng.random() < 0.03:
        m.SANDBOX_TIMEOUTS.inc()
    if rng.random() < 0.05:
        m.INJECTION.inc()
    if rng.random() < 0.05:
        m.SSRF_BLOCKED.labels(rng.choice(["private_ip", "metadata", "bad_port"])).inc()
    if rng.random() < 0.05:
        m.RATE_LIMITED.labels(rng.choice(["ip", "key"])).inc()
    if rng.random() < 0.15:
        m.CAMPAIGN_NEW_DOMAINS.labels(rng.choice(BRANDS), "replay").inc()
        m.BRAND_IMPERSONATION.labels(rng.choice(BRANDS)).inc()
    if rng.random() < 0.05:
        m.USER_FEEDBACK.labels(rng.choice(["false_positive", "false_negative", "confirm"])).inc()
    if rng.random() < 0.04:
        sev = rng.choice(["low", "medium", "high"])
        m.record_incident(type="campaign", severity=sev, source="replay")
        m.RULE_FIRED.labels("R1").inc()
        m.SENTINEL_ACTIONS.labels("draft_takedown", "dry_run").inc()
        m.TIME_TO_INCIDENT.observe(rng.uniform(5, 300))
    # gauges: slow random walks
    state["agree"] = min(1.0, max(0.6, state["agree"] + rng.uniform(-0.01, 0.01)))
    state["drift"] = min(0.4, max(0.0, state["drift"] + rng.uniform(-0.01, 0.01)))
    state["lag"] = max(0.0, state["lag"] + rng.uniform(-2, 2))
    m.ROUTE_AGREEMENT.set(state["agree"])
    m.SCORE_DRIFT.set(state["drift"])
    m.EVENT_LAG.set(state["lag"])
    m.APPROVALS_PENDING.set(rng.choice([0, 0, 1, 2]))
    for sev in ("low", "medium", "high"):
        m.INCIDENT_OPEN.labels(sev).set(rng.randint(0, 3))
    for feed in FEEDS:
        m.FEED_ENABLED.labels(feed).set(1)
        m.FEED_AGE.labels(feed).set(state.setdefault(feed, 0.0) + 1)
        state[feed] = (state[feed] + 1) % 1800
    for name, base in (("f1", 0.9), ("precision", 0.93), ("recall", 0.88)):
        m.EVAL_METRIC.labels(name, "demo", "cascade").set(base + rng.uniform(-0.005, 0.005))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=9199)
    ap.add_argument("--seconds", type=float, default=0, help="stop after N seconds (0 = forever)")
    args = ap.parse_args()

    start_http_server(args.port, addr="0.0.0.0", registry=m.REGISTRY)  # noqa: S104
    TARGETS.parent.mkdir(parents=True, exist_ok=True)
    TARGETS.write_text(
        f"- targets: ['host.docker.internal:{args.port}']\n"
        "  labels: { service: demo-emitter, data: synthetic-replay }\n",
        encoding="utf-8",
    )
    print(f"SYNTHETIC replay metrics on :{args.port}/metrics; target file {TARGETS}")
    rng = random.Random()  # noqa: S311 - demo data, not security
    state = {"agree": 0.92, "drift": 0.05, "lag": 3.0}
    end = time.monotonic() + args.seconds if args.seconds else None
    try:
        while end is None or time.monotonic() < end:
            tick(rng, state)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(FileNotFoundError):
            TARGETS.unlink()


if __name__ == "__main__":
    main()
