#!/usr/bin/env python3
"""T-015 smoke assertions against a RUNNING stack (defanged/fixture inputs only).

Env: FL_GATEWAY_URL (default https://localhost:8443), COMPOSE_PROJECT_NAME (docker compose),
FL_SMOKE_FAKE_WORKER=1 (a test double answers jobs; worker-metric checks are then SKIPPED and
reported as such: only the real worker proves G1), FL_SMOKE_PHISH_URL / FL_SMOKE_OFFICIAL_URL.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import jsonschema
from referencing import Registry, Resource

from falcon_api.canon import canonicalize_url, sha256_hex

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("FL_GATEWAY_URL", "https://localhost:8443").rstrip("/")
FAKE = os.environ.get("FL_SMOKE_FAKE_WORKER") == "1"
PHISH = os.environ.get("FL_SMOKE_PHISH_URL", "http://falcon-demo-bank-secure.test/login")
OFFICIAL = os.environ.get("FL_SMOKE_OFFICIAL_URL", "http://falcon-demo-bank.test/")
SSRF_URL = "http://169.254.169.254/"
FINAL_TIMEOUT_S = 90

docs: list[dict[str, Any]] = []
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, note: str = "") -> None:
    results.append((name, status, note))
    print(f"[{status:4}] {name} {note}".rstrip(), flush=True)


def fresh(url: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}r={secrets.token_hex(4)}"


def compose(*args: str, stdin: str | None = None) -> str:
    cmd = ["docker", "compose", "--profile", "core", "--profile", "obs", *args]
    return subprocess.run(  # noqa: S603
        cmd, cwd=ROOT, input=stdin, capture_output=True, text=True, check=True, timeout=60
    ).stdout


def worker_metric(name: str) -> float | None:
    """Sum of a counter family scraped from the worker container (not published on the host)."""
    try:
        out = compose(
            "exec", "-T", "worker", "python", "-c",
            "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8000/metrics').read().decode())",
        )  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return None
    vals = [float(m.group(1)) for m in re.finditer(rf"(?m)^{name}(?:{{[^}}]*}})? (\S+)$", out)]
    return sum(vals) if vals else 0.0


def validator() -> jsonschema.Draft202012Validator:
    resources = [
        (f.name, Resource.from_contents(json.loads(f.read_text()))) for f in (ROOT / "contracts").glob("*.schema.json")
    ]
    registry: Registry = Registry().with_resources(resources)  # type: ignore[assignment]
    schema = json.loads((ROOT / "contracts" / "verdict.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema, registry=registry)


def submit(c: httpx.Client, url: str, **params: Any) -> httpx.Response:
    return c.post("/v1/check/url", json={"url": url}, params=params, timeout=15)


def final_verdict(c: httpx.Client, url: str) -> dict[str, Any]:
    r = submit(c, url)
    if r.status_code not in (200, 202):
        raise AssertionError(f"submit -> {r.status_code}")
    body = r.json()
    vid = body["verdict_id"]
    deadline = time.monotonic() + FINAL_TIMEOUT_S
    while time.monotonic() < deadline:
        g = c.get(f"/v1/verdicts/{vid}", timeout=10)
        if g.status_code == 200 and g.json().get("final"):
            docs.append(g.json())
            return dict(g.json())
        time.sleep(0.5)
    raise AssertionError(f"no final verdict for {vid} in {FINAL_TIMEOUT_S}s")


def has_rule(doc: dict[str, Any], rule: str) -> bool:
    return any(e.get("hard_rule") == rule for e in doc.get("evidence", []))


def step(name: str, fn: Any) -> None:
    try:
        note = fn()
        record(name, "PASS", note or "")
    except SkipError as exc:
        record(name, "SKIP", str(exc))
    except Exception as exc:  # report every failure, exit non-zero at the end
        record(name, "FAIL", f"{type(exc).__name__}: {exc}")


class SkipError(Exception):
    pass


def main() -> int:
    print(f"smoke: gateway={BASE} worker={'FAKE (test double)' if FAKE else 'real'}")
    c = httpx.Client(base_url=BASE, verify=False, timeout=15)  # noqa: S501 - local CA

    def t_phish() -> str:
        d = final_verdict(c, fresh(PHISH))
        assert d["verdict"] == "dangerous", d["verdict"]
        assert has_rule(d, "H1"), "H1 not cited"
        return d["verdict_id"]

    def t_official() -> str:
        d = final_verdict(c, fresh(OFFICIAL))
        assert d["verdict"] == "no_warning_signs", d["verdict"]
        assert d["actions"].get("caution", {}).get("en"), "caution missing"
        return d["verdict_id"]

    def t_feed() -> str:
        url = f"http://synthetic-openphish.test/{secrets.token_hex(4)}"
        host = "synthetic-openphish.test"
        # feed:openphish stores sha256 hex of the canonical URL and of the host, never plaintext
        hashes = [sha256_hex(canonicalize_url(url)), sha256_hex(host)]
        rc = ("exec", "-T", "redis", "redis-cli")
        prior_ts = compose(*rc, "GET", "feed:openphish:updated_at").strip()
        prior_members = set(compose(*rc, "SMEMBERS", "feed:openphish").split())
        added = [h for h in hashes if h not in prior_members]
        try:
            compose(*rc, "SADD", "feed:openphish", *hashes)
            # H2 needs a fresh mirror (< 6 h): mark the mirror as just refreshed for the duration of this step.
            compose(*rc, "SET", "feed:openphish:updated_at", str(time.time()))
            d = final_verdict(c, url)
            assert d["verdict"] == "dangerous", d["verdict"]
            assert has_rule(d, "H2"), "H2 not cited"
            assert any(e["tier"] == "T0" for e in d["evidence"]), "not decided at T0"
        finally:  # restore the mirror exactly as found
            if added:
                compose(*rc, "SREM", "feed:openphish", *added)
            if prior_ts:
                compose(*rc, "SET", "feed:openphish:updated_at", prior_ts)
            else:
                compose(*rc, "DEL", "feed:openphish:updated_at")
        return d["verdict_id"]

    def t_ssrf() -> str:
        before = None if FAKE else worker_metric("fl_ssrf_blocked_total")
        url = fresh(SSRF_URL)  # fresh: a cached verdict would not re-trigger the guard
        r = submit(c, url)
        if r.status_code in (400, 403, 422):
            note = f"rejected at API ({r.status_code})"
        else:
            d = final_verdict(c, url)
            assert d["verdict"] != "no_warning_signs", "metadata IP not rejected"
            assert d["degraded"] or d["verdict"] == "dangerous", "expected degraded or dangerous"
            note = f"verdict={d['verdict']} degraded={d['degraded']}"
        if FAKE:
            return note + "; metric check skipped (fake worker)"
        after = worker_metric("fl_ssrf_blocked_total")
        assert before is not None and after is not None and after >= before + 1, (before, after)
        return note + f"; fl_ssrf_blocked_total {before:g}->{after:g}"

    def t_sse() -> str:
        r = submit(c, fresh(PHISH))
        vid = r.json()["verdict_id"]
        events: list[dict[str, Any]] = []
        with c.stream("GET", f"/v1/verdicts/{vid}/events", timeout=FINAL_TIMEOUT_S) as s:
            assert s.headers["content-type"].startswith("text/event-stream")
            for line in s.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        docs.extend(events)
        assert len(events) >= 2, f"{len(events)} events"
        assert {e["verdict_id"] for e in events} == {vid}
        assert events[-1]["final"] is True and not any(e["final"] for e in events[:-1])
        return f"{len(events)} events"

    def t_wait() -> str:
        t0 = time.monotonic()
        r = submit(c, fresh(PHISH), wait=8)
        took = time.monotonic() - t0
        assert took <= 8.5, f"{took:.2f}s"
        assert r.status_code in (200, 202), r.status_code
        body = r.json()
        if "verdict" in body:
            docs.append(body)
        return f"{r.status_code} in {took:.1f}s"

    def t_schema() -> str:
        v = validator()
        assert docs, "no verdicts collected"
        for d in docs:
            v.validate(d)
            assert d.get("screenshot_url") is None, "anonymous got screenshot_url"
        return f"{len(docs)} documents valid"

    checks_before = None if FAKE else worker_metric("fl_checks_total")

    def t_metrics() -> str:
        if FAKE:
            raise SkipError("fake worker exposes no fl_checks_total")
        after = worker_metric("fl_checks_total")
        assert checks_before is not None and after is not None and after > checks_before
        return f"fl_checks_total {checks_before:g}->{after:g}"

    step("1 fixture phish -> dangerous, H1 cited", t_phish)
    step("2 fixture official -> no_warning_signs + caution", t_official)
    step("3 feed:openphish synthetic entry -> dangerous via H2 at T0", t_feed)
    step("4 169.254.169.254 rejected + fl_ssrf_blocked_total", t_ssrf)
    step("5 SSE >=2 events, same verdict_id, last final", t_sse)
    step("6 ?wait=8 within budget", t_wait)
    step("7 all responses validate against verdict.schema.json", t_schema)
    step("8 fl_checks_total increased", t_metrics)

    failed = [r for r in results if r[1] == "FAIL"]
    skipped = [r for r in results if r[1] == "SKIP"]
    print(
        f"\nsmoke: {len(results) - len(failed) - len(skipped)} passed, "
        f"{len(failed)} failed, {len(skipped)} skipped" + ("  [FAKE WORKER: NOT a G1 result]" if FAKE else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
