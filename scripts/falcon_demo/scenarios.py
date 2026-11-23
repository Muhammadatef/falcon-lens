"""`make demo` scenario run: the six docs/DEMO.md scenarios and the Sentinel scene, against the running stack.

What it does:
    Sends each scenario's input through the real API and checks the outcome the demo script promises
    (verdict class and the hard rule or evidence it cites). Prints a table with one row per scenario:
    PASS, FAIL or SKIPPED, the verdict, the verdict id and a note. Exit code is 1 when any row FAILED.
    A SKIPPED row never counts as a pass: the summary line lists it as "not run".

    1  feed phish (H2)   needs a private feed mirror (data/private/feeds/openphish/ not empty). Without it: SKIPPED.
                         With it, the check uses an invented `.test` host that is added to the Redis feed set
                         for the duration of the step and removed again. Live feed entries are never submitted.
    2  lookalike         falcon-demo-bank-secure.test/login   -> dangerous, rule H1
    3  Arabic SMS        synthetic message with the scenario 2 link -> dangerous, rule H5
    4  email             synthetic .eml                      -> dangerous or suspicious, display-name evidence
    5  verified official falcon-demo-bank.test               -> no_warning_signs, rule H3
    6  injected page     falcon-demo-bank-injection.test     -> not no_warning_signs, injection evidence present
    S  Sentinel scene    only when the sentinel container is healthy: short labelled replay, then a campaign
                         incident of this run must exist with an internal action executed and an external
                         draft awaiting approval. Nothing is approved or sent. Otherwise SKIPPED.

When to use it:
    Called by `make demo` after the stack is up and seeded. Direct form:
    PYTHONPATH=scripts uv run python -m falcon_demo scenarios [--no-sentinel]

Inputs / outputs:
    .env (ports, FL_MCP_SERVICE_KEY or FL_SANDBOX_API_KEY, FL_OPERATOR_KEY). Reads and writes no files; the
    only side effects are checks labelled source=replay and, for scenario 1, a temporary Redis feed entry.

Safety notes:
    Only invented Falcon Demo Bank `.test` fixtures. Nothing is approved, sent or submitted anywhere.
"""

from __future__ import annotations

import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .common import SOURCE, Endpoints, load_env, pick_key

ROOT = Path(__file__).resolve().parents[2]
FEED_DIR = ROOT / "data" / "private" / "feeds" / "openphish"
FINAL_TIMEOUT_S = 90.0

# Synthetic, invented for the demo (docs/DEMO.md scenario 3). No real brand, no real person.
SMS_TEXT = (
    "عزيزي العميل، حسابك في بنك الصقر التجريبي سيتم تجميده خلال ساعة. "
    "أرسل رمز التحقق الذي وصلك وادخل على http://falcon-demo-bank-secure.test/login للتحديث فوراً"
)
# Reserved-style invented sender; the link text differs from its target (scenario 4).
EML = (
    'From: "Falcon Demo Bank" <alerts@example-mailer.invalid>\r\n'
    "To: customer@example.invalid\r\n"
    "Subject: Verify your Falcon Demo Bank account\r\n"
    "Date: Mon, 23 Nov 2026 08:00:00 +0000\r\n"
    "Message-ID: <demo-s4@example-mailer.invalid>\r\n"
    "MIME-Version: 1.0\r\n"
    "Content-Type: text/html; charset=utf-8\r\n\r\n"
    '<html><body><p>Your account is limited. <a href="http://falcon-demo-bank-secure.test/login">'
    "http://falcon-demo-bank.test/verify</a></p></body></html>\r\n"
)

PASS, FAIL, SKIPPED = "PASS", "FAIL", "SKIPPED"


@dataclass
class Row:
    name: str
    status: str
    verdict: str = ""
    verdict_id: str = ""
    note: str = ""


class CheckFailed(Exception):
    """A scenario outcome differs from what docs/DEMO.md promises."""


def expect(cond: object, message: str) -> None:
    if not cond:
        raise CheckFailed(message)


class Scenario(Exception):
    """Raised by a scenario to mark itself SKIPPED (reason in the message)."""


def has_rule(doc: Mapping[str, Any], rule: str) -> bool:
    """True if any evidence item of the verdict cites the hard rule."""
    return any(e.get("hard_rule") == rule for e in doc.get("evidence", []))


def has_signal(doc: Mapping[str, Any], signal: str) -> bool:
    """True if any evidence item of the verdict has this signal id."""
    return any(e.get("signal") == signal for e in doc.get("evidence", []))


def allowlist_hint(doc: Mapping[str, Any]) -> str:
    """What to do when a fixture host was refused as an internal name: the running stack's allowlist is stale.

    `.env` overrides the compose default of FL_SSRF_ALLOW_HOSTS, so an `.env` copied before a fixture host was
    added keeps blocking it (seen on the demo stack: the injection, cloak and bot-relay hosts were missing)."""
    if "not_rendered:internal_name" not in (doc.get("degraded_reasons") or []):
        return ""
    return (
        "; FL_SSRF_ALLOW_HOSTS in .env is missing this fixture host: copy that line from .env.example, "
        "then `docker compose up -d worker sandbox egress-proxy`"
    )


def fresh(url: str) -> str:
    """Add a throwaway query so an earlier cached verdict for the same URL is not returned."""
    return f"{url}{'&' if '?' in url else '?'}run={secrets.token_hex(4)}"


class Runner:
    def __init__(self, env: Mapping[str, str], client: httpx.Client | None = None) -> None:
        self.env = env
        self.ep = Endpoints.from_env(env)
        key, _ = pick_key(env)
        self.key = key
        local = self.ep.gateway.startswith(("https://localhost", "https://127.0.0.1"))
        self.c = client or httpx.Client(base_url=self.ep.gateway, timeout=40.0, verify=not local)

    def _headers(self) -> dict[str, str]:
        h = {"X-Falcon-Source": SOURCE, "Idempotency-Key": "demo-" + secrets.token_hex(8)}
        if self.key:
            h["X-API-Key"] = self.key
        return h

    def _final(self, r: httpx.Response) -> dict[str, Any]:
        if r.status_code not in (200, 202):
            raise CheckFailed(f"submit -> HTTP {r.status_code}")
        doc: dict[str, Any] = r.json()
        vid = doc["verdict_id"]
        deadline = time.monotonic() + FINAL_TIMEOUT_S
        while time.monotonic() < deadline:
            if doc.get("verdict") and doc.get("final", True):
                return doc
            time.sleep(1.0)
            g = self.c.get(f"/v1/verdicts/{vid}", headers=self._headers())
            if g.status_code == 200:
                doc = g.json()
        raise CheckFailed(f"no final verdict for {vid} in {FINAL_TIMEOUT_S:.0f}s")

    def url(self, url: str) -> dict[str, Any]:
        r = self.c.post("/v1/check/url", params={"wait": 20}, json={"url": url}, headers=self._headers())
        return self._final(r)

    def message(self, text: str) -> dict[str, Any]:
        return self._final(
            self.c.post("/v1/check/message", params={"wait": 20}, json={"text": text}, headers=self._headers())
        )

    def email(self, eml: str) -> dict[str, Any]:
        files = {"file": ("demo.eml", eml.encode(), "message/rfc822")}
        return self._final(self.c.post("/v1/check/email", params={"wait": 20}, files=files, headers=self._headers()))


def _compose(*args: str) -> str:
    return subprocess.run(["docker", "compose", *args], check=True, capture_output=True, text=True, cwd=ROOT).stdout


def s1_feed(r: Runner) -> tuple[dict[str, Any], str]:
    if not FEED_DIR.is_dir() or not any(FEED_DIR.iterdir()):
        raise Scenario("no private feed mirror (data/private/feeds/openphish/ is absent or empty)")
    from falcon_api.canon import canonicalize_url, sha256_hex  # lazy: only needed when the mirror is present

    host = "demo-feed-entry.test"
    url = f"http://{host}/{secrets.token_hex(4)}"
    hashes = [sha256_hex(canonicalize_url(url)), sha256_hex(host)]
    rc = ("exec", "-T", "redis", "redis-cli")
    prior_ts = _compose(*rc, "GET", "feed:openphish:updated_at").strip()
    prior = set(_compose(*rc, "SMEMBERS", "feed:openphish").split())
    added = [h for h in hashes if h not in prior]
    try:
        _compose(*rc, "SADD", "feed:openphish", *hashes)
        _compose(*rc, "SET", "feed:openphish:updated_at", str(time.time()))
        d = r.url(url)
    finally:
        if added:
            _compose(*rc, "SREM", "feed:openphish", *added)
        if prior_ts:
            _compose(*rc, "SET", "feed:openphish:updated_at", prior_ts)
        else:
            _compose(*rc, "DEL", "feed:openphish:updated_at")
    expect(d["verdict"] == "dangerous" and has_rule(d, "H2"), f"expected dangerous via H2, got {d['verdict']}")
    return d, "H2 via an invented .test feed entry (restored afterwards)"


def s2_lookalike(r: Runner) -> tuple[dict[str, Any], str]:
    d = r.url(fresh("http://falcon-demo-bank-secure.test/login"))
    expect(d["verdict"] == "dangerous", f"expected dangerous, got {d['verdict']}")
    expect(has_rule(d, "H1"), "rule H1 not cited")
    return d, "H1 cited"


def s3_sms(r: Runner) -> tuple[dict[str, Any], str]:
    d = r.message(SMS_TEXT)
    expect(d["verdict"] == "dangerous", f"expected dangerous, got {d['verdict']}")
    expect(has_rule(d, "H5"), "rule H5 not cited")
    return d, "H5 cited"


def s4_email(r: Runner) -> tuple[dict[str, Any], str]:
    d = r.email(EML)
    expect(d["verdict"] in ("dangerous", "suspicious"), f"expected dangerous or suspicious, got {d['verdict']}")
    expect(has_signal(d, "email.display_name_impersonation"), "display-name impersonation evidence missing")
    return d, "display-name impersonation evidence"


def s5_official(r: Runner) -> tuple[dict[str, Any], str]:
    d = r.url(fresh("http://falcon-demo-bank.test/"))
    expect(d["verdict"] == "no_warning_signs", f"expected no_warning_signs, got {d['verdict']}")
    expect(has_rule(d, "H3"), "rule H3 not cited")
    expect(d.get("actions", {}).get("caution", {}).get("en"), "caution reminder missing")
    return d, "H3 cited, caution present"


def s6_injection(r: Runner) -> tuple[dict[str, Any], str]:
    d = r.url(fresh("http://falcon-demo-bank-injection.test/"))
    expect(d["verdict"] != "no_warning_signs", "injected page was cleared")
    expect(not d.get("degraded"), f"page not rendered: {d.get('degraded_reasons')}{allowlist_hint(d)}")
    expect(has_signal(d, "injection.instruction_like_text"), "injection evidence missing")
    return d, "instruction-like text counted as risk evidence"


SCENARIOS: tuple[tuple[str, Callable[[Runner], tuple[dict[str, Any], str]]], ...] = (
    ("1 feed phish (H2)", s1_feed),
    ("2 lookalike", s2_lookalike),
    ("3 Arabic SMS", s3_sms),
    ("4 phishing email", s4_email),
    ("5 verified official", s5_official),
    ("6 injected page", s6_injection),
)


def sentinel_healthy() -> bool:
    """True when the compose sentinel container reports healthy."""
    try:
        cid = _compose("ps", "-q", "sentinel").strip()
        if not cid:
            return False
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", cid], capture_output=True, text=True, check=True
        ).stdout.strip()
        return out == "healthy"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def sentinel_scene(
    r: Runner, *, replay_seconds: int = 90, wait_s: float = 150.0, healthy: Callable[[], bool] = sentinel_healthy
) -> tuple[dict[str, Any], str]:
    """Short replay, then the planted campaign incident of this run must show executed + awaiting-approval actions."""
    if not healthy():
        # A FAIL, not a SKIP: the Sentinel is one of the two agents the demo shows, and a restart-looping
        # container must never let `make demo` exit 0 (audit 2026-11-23).
        raise CheckFailed(
            "sentinel container is not healthy: `docker compose ps sentinel`, then "
            "`docker compose up -d --build sentinel` (see docs/RUNBOOK.md#service-down)"
        )
    op = r.env.get("FL_OPERATOR_KEY")
    if not op:
        raise Scenario("FL_OPERATOR_KEY not set")
    from . import replay

    started = datetime.now(UTC)
    rc = replay.main(["--rate", "1/s", "--duration", f"{replay_seconds}s"])
    expect(rc == 0, f"replay exited {rc}")
    hdr = {"Authorization": f"Bearer {op}"}
    deadline = time.monotonic() + wait_s
    last = "no campaign incident from this run yet"
    while time.monotonic() < deadline:
        g = r.c.get("/v1/incidents", params={"limit": 25}, headers=hdr)
        expect(g.status_code == 200, f"/v1/incidents -> HTTP {g.status_code}")
        for inc in g.json().get("items", []):
            touched = datetime.fromisoformat(str(inc["updated_at"]).replace("Z", "+00:00"))
            if inc["type"] != "campaign" or touched < started:
                continue
            acts = inc.get("actions", [])
            done = [a for a in acts if a["mode"] == "internal_auto" and a["status"] == "executed"]
            wait = [a for a in acts if a["mode"] == "external_draft" and a["status"] == "awaiting_approval"]
            last = f"{inc['incident_id']} status={inc['status']} executed={len(done)} awaiting_approval={len(wait)}"
            if done and wait:
                return {"verdict": inc["status"], "verdict_id": inc["incident_id"]}, last
        time.sleep(5)
    raise CheckFailed(last)


def run_all(r: Runner, *, sentinel: bool = True, healthy: Callable[[], bool] = sentinel_healthy) -> list[Row]:
    rows: list[Row] = []
    plan: list[tuple[str, Callable[[], tuple[dict[str, Any], str]]]] = [(n, lambda f=f: f(r)) for n, f in SCENARIOS]  # type: ignore[misc]
    if sentinel:
        plan.append(("S Sentinel scene", lambda: sentinel_scene(r, healthy=healthy)))
    for name, fn in plan:
        try:
            doc, note = fn()
            rows.append(Row(name, PASS, str(doc.get("verdict", "")), str(doc.get("verdict_id", "")), note))
        except Scenario as exc:
            rows.append(Row(name, SKIPPED, note=str(exc)))
        except (CheckFailed, httpx.HTTPError, KeyError, subprocess.CalledProcessError) as exc:
            rows.append(Row(name, FAIL, note=f"{type(exc).__name__}: {exc}"[:320]))
    return rows


def render(rows: list[Row]) -> str:
    lines = [f"{'scenario':<22} {'result':<8} {'verdict':<18} {'id':<34} note"]
    lines += [f"{x.name:<22} {x.status:<8} {x.verdict:<18} {x.verdict_id:<34} {x.note}" for x in rows]
    n = {s: sum(x.status == s for x in rows) for s in (PASS, FAIL, SKIPPED)}
    lines.append(f"scenarios: {n[PASS]} passed, {n[FAIL]} failed, {n[SKIPPED]} not run (SKIPPED is not a pass)")
    return "\n".join(lines)


def exit_code(rows: list[Row]) -> int:
    """1 when any scenario FAILED; SKIPPED rows do not fail the run but are reported as not run."""
    return 1 if any(x.status == FAIL for x in rows) else 0


def main(argv: list[str]) -> int:
    env = load_env()
    r = Runner(env)
    try:
        rows = run_all(r, sentinel="--no-sentinel" not in argv)
    finally:
        r.c.close()
    print(render(rows))
    return exit_code(rows)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
