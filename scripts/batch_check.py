#!/usr/bin/env python3
"""Batch URL checker: submit a list of URLs to a RUNNING Falcon Lens API and write one CSV row per URL.

What it does:
    Reads one URL per line (blank lines and `#` comments skipped) or a CSV with a `url` column (and an
    optional `label` column holding fraud/legit). Submits each URL to POST /v1/check/url, waits for the final
    verdict, and writes a CSV: url, verdict, risk_score, binary_label, degraded, degraded_reasons,
    tier_reached, top_reasons, latency_ms, verdict_id, error.

When to use it:
    To run your own test set (for example a list handed over by a judge) through the real cascade.

How to run:
    make batch FILE=urls.txt [OUT=results.csv] [CONCURRENCY=4] [MODE=strict|lenient]
    uv run python scripts/batch_check.py urls.txt --out results.csv --concurrency 4 --mode strict

Inputs:
    FILE as above. Env: FL_BATCH_BASE_URL (default https://localhost:8443), FL_BATCH_API_KEY (else
    FL_OPERATOR_KEY, read from the environment or from .env in-process, never printed),
    FL_BATCH_CA_BUNDLE (PEM of the local CA; without it a localhost gateway is trusted unverified).

Outputs / side effects:
    The CSV (default results.csv). Re-running with the same OUT resumes: URLs already answered are kept and
    skipped; rows that ended as could_not_check are retried. Every submitted URL becomes a normal check in
    the running stack (database rows, counters). Falcon Lens loads suspicious pages only in its sandbox.

Binary label mapping (docs/EVALS.md):
    strict (default): fraud = dangerous OR suspicious (suspicious means "warn the user").
    lenient:          fraud = dangerous only.
    could_not_check:  fraud in strict, legit in lenient for the binary column, and always reported separately.
    could_not_check means: rejected by the API (bad URL, blocked target), network error, or no final verdict
    before the per-URL timeout.

Safety notes:
    Never prints the API key. Respects 429 with Retry-After and exponential backoff.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import io
import math
import os
import random
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
VERDICTS = ("dangerous", "suspicious", "no_warning_signs")
COULD_NOT_CHECK = "could_not_check"
FIELDS = [
    "url",
    "verdict",
    "risk_score",
    "binary_label",
    "degraded",
    "degraded_reasons",
    "tier_reached",
    "top_reasons",
    "latency_ms",
    "verdict_id",
    "error",
]
MAX_URLS = 5000
FINAL_TIMEOUT_S = 90.0
MAX_RETRIES_429 = 8


# ---------------------------------------------------------------- input


def parse_input(text: str) -> list[tuple[str, str | None]]:
    """Return (url, label) pairs. CSV when the first line has a `url` header, else one URL per line."""
    lines = [ln for ln in text.lstrip("﻿").splitlines()]
    first = next((ln for ln in lines if ln.strip()), "")
    header = [h.strip().lower() for h in next(csv.reader([first]), [])] if first else []
    out: list[tuple[str, str | None]] = []
    if "url" in header:
        for row in csv.DictReader(io.StringIO("\n".join(lines))):
            norm = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if isinstance(k, str)}
            url = norm.get("url", "")
            if url:
                out.append((url, normalise_label(norm.get("label"))))
        return out
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith("#"):
            out.append((s, None))
    return out


def normalise_label(raw: str | None) -> str | None:
    """Map a free-form label to fraud / legit / None."""
    v = (raw or "").strip().lower()
    if v in {"fraud", "phish", "phishing", "malicious", "scam", "1", "bad"}:
        return "fraud"
    if v in {"legit", "legitimate", "benign", "safe", "0", "good"}:
        return "legit"
    return None


# ---------------------------------------------------------------- mapping


def binary_label(verdict: str, mode: str) -> str:
    """fraud / legit for one verdict in the given mode (could_not_check: fraud in strict, legit in lenient)."""
    if mode not in ("strict", "lenient"):
        raise ValueError(f"mode must be strict or lenient, not {mode!r}")
    if verdict == "dangerous":
        return "fraud"
    if verdict == "suspicious":
        return "fraud" if mode == "strict" else "legit"
    if verdict == COULD_NOT_CHECK:
        return "fraud" if mode == "strict" else "legit"
    return "legit"


def top_reason_codes(doc: dict[str, Any], limit: int = 3) -> list[str]:
    """Signal codes behind the verdict: those cited by its reasons first, then the heaviest risk evidence."""
    by_id = {e.get("id"): e for e in doc.get("evidence") or [] if isinstance(e, dict)}
    codes: list[str] = []

    def add(code: str | None) -> None:
        if code and code not in codes:
            codes.append(code)

    for r in doc.get("reasons") or []:
        for eid in r.get("evidence_ids") or []:
            ev = by_id.get(eid)
            if ev:
                add(ev.get("hard_rule") or ev.get("signal"))
    risky = sorted(
        (e for e in by_id.values() if e.get("polarity") == "risk" or (e.get("weight") or 0) > 0),
        key=lambda e: -(e.get("weight") or 0),
    )
    for e in risky:
        add(e.get("hard_rule") or e.get("signal"))
    return codes[:limit]


def row_from_verdict(url: str, doc: dict[str, Any], mode: str, latency_ms: int) -> dict[str, str]:
    """One CSV row from a final verdict document."""
    verdict = str(doc.get("verdict", ""))
    if verdict not in VERDICTS:
        return row_unchecked(url, f"unexpected verdict {verdict!r}", mode, latency_ms)
    return {
        "url": url,
        "verdict": verdict,
        "risk_score": str(doc.get("risk_score", "")),
        "binary_label": binary_label(verdict, mode),
        "degraded": str(bool(doc.get("degraded"))).lower(),
        "degraded_reasons": ";".join(doc.get("degraded_reasons") or []),
        "tier_reached": str(doc.get("tier_reached", "")),
        "top_reasons": ";".join(top_reason_codes(doc)),
        "latency_ms": str(doc.get("latency_ms", latency_ms)),
        "verdict_id": str(doc.get("verdict_id", "")),
        "error": "",
    }


def row_unchecked(url: str, error: str, mode: str, latency_ms: int = 0, verdict_id: str = "") -> dict[str, str]:
    """A could_not_check row."""
    return {
        "url": url,
        "verdict": COULD_NOT_CHECK,
        "risk_score": "",
        "binary_label": binary_label(COULD_NOT_CHECK, mode),
        "degraded": "",
        "degraded_reasons": "",
        "tier_reached": "",
        "top_reasons": "",
        "latency_ms": str(latency_ms),
        "verdict_id": verdict_id,
        "error": error[:200],
    }


# ---------------------------------------------------------------- statistics


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k successes out of n (95% by default)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def metrics(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Confusion counts and precision/recall/F1/FPR with Wilson CIs from (truth, predicted) pairs."""
    tp = sum(1 for t, p in pairs if t == "fraud" and p == "fraud")
    fp = sum(1 for t, p in pairs if t == "legit" and p == "fraud")
    fn = sum(1 for t, p in pairs if t == "fraud" and p == "legit")
    tn = sum(1 for t, p in pairs if t == "legit" and p == "legit")

    def rate(k: int, n: int) -> dict[str, Any]:
        lo, hi = wilson(k, n)
        return {"value": (k / n) if n else None, "ci95": (lo, hi), "k": k, "n": n}

    precision, recall, fpr = rate(tp, tp + fp), rate(tp, tp + fn), rate(fp, fp + tn)
    p, r = precision["value"], recall["value"]
    f1 = (2 * p * r / (p + r)) if p is not None and r is not None and (p + r) > 0 else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "fpr": fpr, "f1": f1}


def _fmt(m: dict[str, Any]) -> str:
    v = m["value"]
    if v is None:
        return "n/a"
    lo, hi = m["ci95"]
    return f"{v:.3f} [{lo:.3f}, {hi:.3f}] ({m['k']}/{m['n']})"


def summarise(rows: list[dict[str, str]], labels: dict[str, str | None]) -> str:
    """Human-readable summary: verdict counts, could_not_check, and metrics for both modes if labels exist."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    degraded = sum(1 for r in rows if r["degraded"] == "true")
    lat = sorted(int(r["latency_ms"]) for r in rows if r["latency_ms"].isdigit() and r["verdict"] != COULD_NOT_CHECK)
    out = [f"URLs: {len(rows)}"]
    for v in (*VERDICTS, COULD_NOT_CHECK):
        out.append(f"  {v}: {counts.get(v, 0)}")
    out.append(f"  degraded: {degraded}")
    if lat:
        out.append(f"  latency_ms median {lat[len(lat) // 2]}, max {lat[-1]}")
    truth = {r["url"]: labels.get(r["url"]) for r in rows}
    if any(truth.values()):
        for mode in ("strict", "lenient"):
            pairs = [(t, binary_label(r["verdict"], mode)) for r in rows if (t := truth[r["url"]])]
            checked = [
                (t, binary_label(r["verdict"], mode))
                for r in rows
                if (t := truth[r["url"]]) and r["verdict"] != COULD_NOT_CHECK
            ]
            unchecked = len(pairs) - len(checked)
            m = metrics(pairs)
            out.append(
                f"Metrics, {mode} mode ({len(pairs)} labelled, could_not_check={binary_label(COULD_NOT_CHECK, mode)}):"
            )
            out.append(f"  precision {_fmt(m['precision'])}")
            out.append(f"  recall    {_fmt(m['recall'])}")
            out.append(f"  F1        {'n/a' if m['f1'] is None else f'{m["f1"]:.3f}'}")
            out.append(f"  FPR       {_fmt(m['fpr'])}")
            out.append(f"  TP {m['tp']} FP {m['fp']} FN {m['fn']} TN {m['tn']}")
            if unchecked:
                mc = metrics(checked)
                out.append(
                    f"  excluding {unchecked} could_not_check: P {_fmt(mc['precision'])}, R {_fmt(mc['recall'])}"
                )
    return "\n".join(out)


# ---------------------------------------------------------------- API client


def load_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines of a .env file (no export, no interpolation). Values never leave this process."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for ln in path.read_text().splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip("\"'")
    return env


def resolve_key(environ: dict[str, str] | None = None, env_file: Path | None = None) -> str | None:
    """API key: FL_BATCH_API_KEY, then FL_OPERATOR_KEY, from the environment first and .env second.

    Never FL_WEB_READ_KEY: it is read-scope and cannot POST /v1/check/url.
    """
    e = dict(os.environ) if environ is None else environ
    f = load_env_file(env_file or ROOT / ".env")
    for name in ("FL_BATCH_API_KEY", "FL_OPERATOR_KEY"):
        v = e.get(name) or f.get(name)
        if v:
            return v
    return None


def retry_after(resp: httpx.Response, attempt: int) -> float:
    """Seconds to wait after a 429: the Retry-After header if numeric, else exponential backoff with jitter."""
    raw = resp.headers.get("retry-after", "")
    try:
        return min(60.0, max(0.0, float(raw)))
    except ValueError:
        return min(30.0, 0.5 * 2**attempt) + random.uniform(0, 0.25)  # noqa: S311 - jitter, not security


class KeyScopeError(Exception):
    """The API refused the key (401/403): every further URL would fail the same way, so the run stops."""


Sleep = Callable[[float], Awaitable[None]]


async def check_one(
    client: httpx.AsyncClient,
    url: str,
    mode: str,
    *,
    sleep: Sleep = asyncio.sleep,
    final_timeout: float = FINAL_TIMEOUT_S,
    poll_s: float = 0.5,
    on_backoff: Callable[[float], None] | None = None,
) -> dict[str, str]:
    """Submit one URL and wait for its final verdict. Never raises: failures become could_not_check rows."""
    t0 = time.monotonic()
    ms = lambda: int((time.monotonic() - t0) * 1000)  # noqa: E731

    async def call(method: str, path: str, **kw: Any) -> httpx.Response:
        for attempt in range(MAX_RETRIES_429 + 1):
            resp = await client.request(method, path, **kw)
            if resp.status_code != 429 or attempt == MAX_RETRIES_429:
                return resp
            wait = retry_after(resp, attempt)
            if on_backoff:
                on_backoff(wait)
            await sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover

    if not is_http_url(url):
        return row_unchecked(url, "not_http_url", mode)
    try:
        r = await call("POST", "/v1/check/url", json={"url": url}, params={"wait": 8})
        if r.status_code in (401, 403):
            raise KeyScopeError(
                f"key lacks check scope (HTTP {r.status_code}): set FL_BATCH_API_KEY to a key with the `check` scope"
            )
        if r.status_code not in (200, 202):
            return row_unchecked(url, f"submit HTTP {r.status_code}", mode, ms())
        doc = r.json()
        vid = str(doc.get("verdict_id", ""))
        deadline = time.monotonic() + final_timeout
        while not doc.get("final"):
            if not vid or time.monotonic() > deadline:
                return row_unchecked(url, "no final verdict in time", mode, ms(), vid)
            await sleep(poll_s)
            g = await call("GET", f"/v1/verdicts/{vid}")
            if g.status_code == 200:
                doc = g.json()
            elif g.status_code not in (202, 404):
                return row_unchecked(url, f"poll HTTP {g.status_code}", mode, ms(), vid)
        return row_from_verdict(url, doc, mode, ms())
    except (httpx.HTTPError, ValueError) as exc:
        return row_unchecked(url, f"{type(exc).__name__}", mode, ms())


# ---------------------------------------------------------------- resume + run


_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: str) -> str:
    """Neutralise a cell a spreadsheet would run as a formula (leading = + - @ tab CR) with a leading quote."""
    return "'" + value if value.startswith(_FORMULA) else value


def csv_unsafe(value: str) -> str:
    """Inverse of csv_safe, so a resumed row matches the URL as given."""
    return value[1:] if value.startswith("'") and value[1:].startswith(_FORMULA) else value


def safe_row(row: dict[str, str]) -> dict[str, str]:
    return {k: csv_safe(v) for k, v in row.items()}


def is_http_url(url: str) -> bool:
    """Only http(s) URLs with a host are submitted."""
    try:
        u = urlsplit(url.strip())
    except ValueError:  # e.g. a defanged host such as a[.]test with a stray bracket
        return False
    return u.scheme.lower() in ("http", "https") and bool(u.netloc)


def load_done(path: Path) -> dict[str, dict[str, str]]:
    """Rows already answered in a partial OUT file (could_not_check rows are retried, so excluded)."""
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("url") and r.get("verdict") in VERDICTS]
    return {csv_unsafe(r["url"]): {k: csv_unsafe(r.get(k, "")) for k in FIELDS} for r in rows}


def rebind(row: dict[str, str], mode: str) -> dict[str, str]:
    """Recompute binary_label for a resumed row so the file always matches the requested mode."""
    row = dict(row)
    row["binary_label"] = binary_label(row["verdict"], mode)
    return row


def render_progress(done: int, total: int, width: int = 30) -> str:
    """Text progress bar."""
    filled = int(width * done / total) if total else width
    return f"[{'#' * filled}{'.' * (width - filled)}] {done}/{total}"


async def run_batch(
    client: httpx.AsyncClient,
    items: list[tuple[str, str | None]],
    out: Path,
    mode: str,
    concurrency: int,
    *,
    sleep: Sleep = asyncio.sleep,
    progress: Callable[[str], None] | None = None,
    final_timeout: float = FINAL_TIMEOUT_S,
) -> tuple[list[dict[str, str]], dict[str, str | None]]:
    """Check every URL (skipping those already in OUT), writing OUT as rows arrive. Returns rows in input order."""
    labels: dict[str, str | None] = {}
    ordered: list[str] = []
    for url, lab in items:
        if url not in labels:
            ordered.append(url)
        labels[url] = lab or labels.get(url)
    done = {u: rebind(r, mode) for u, r in load_done(out).items() if u in labels}
    todo = [u for u in ordered if u not in done]
    results: dict[str, dict[str, str]] = dict(done)
    # Rewrite the file with the kept rows first so a crash never loses them.
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for u in ordered:
            if u in done:
                w.writerow(safe_row(done[u]))
        f.flush()
        sem = asyncio.Semaphore(max(1, concurrency))
        count = len(done)
        fatal: KeyScopeError | None = None

        async def worker(u: str) -> None:
            nonlocal count, fatal
            async with sem:
                if fatal:
                    return
                try:
                    row = await check_one(client, u, mode, sleep=sleep, final_timeout=final_timeout)
                except KeyScopeError as exc:
                    fatal = fatal or exc
                    return
            results[u] = row
            w.writerow(safe_row(row))
            f.flush()
            count += 1
            if progress:
                progress(render_progress(count, len(ordered)))

        if progress:
            progress(render_progress(count, len(ordered)))
        await asyncio.gather(*(worker(u) for u in todo))
        if fatal:
            raise fatal
    rows = [results[u] for u in ordered]
    # Final pass: write in input order so the file is stable and diffable.
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(safe_row(r) for r in rows)
    return rows, labels


def make_client(base: str, key: str | None, ca_bundle: str | None) -> httpx.AsyncClient:
    """Async client for the API. Trust the given CA bundle; localhost without one is trusted unverified."""
    headers = {"accept": "application/json"}
    if key:
        headers["x-api-key"] = key
    verify: bool | str = True
    if ca_bundle:
        verify = ca_bundle
    elif httpx.URL(base).host in ("localhost", "127.0.0.1", "::1"):
        verify = False  # noqa: S501 - local CA gateway only
    return httpx.AsyncClient(base_url=base.rstrip("/"), headers=headers, verify=verify, timeout=20)


async def amain(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"input file not found: {path}", file=sys.stderr)
        return 2
    items = parse_input(path.read_text(encoding="utf-8"))
    if not items:
        print("no URLs found in the input", file=sys.stderr)
        return 2
    if len(items) > MAX_URLS:
        print(f"too many URLs ({len(items)} > {MAX_URLS}); split the file", file=sys.stderr)
        return 2
    env = {**load_env_file(ROOT / ".env"), **os.environ}
    base = args.base_url or env.get("FL_BATCH_BASE_URL") or "https://localhost:8443"
    client = make_client(base, resolve_key(), env.get("FL_BATCH_CA_BUNDLE"))
    out = Path(args.out)

    def progress(s: str) -> None:
        print(f"\r{s}", end="", file=sys.stderr, flush=True)

    try:
        async with client:
            rows, labels = await run_batch(client, items, out, args.mode, args.concurrency, progress=progress)
    except KeyScopeError as exc:
        print(f"\nstopped: {exc}. Rows answered so far are kept in {out}.", file=sys.stderr)
        return 3
    print(file=sys.stderr)
    print(summarise(rows, labels))
    print(f"wrote {out} (mode {args.mode})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check a list of URLs against a running Falcon Lens API.")
    ap.add_argument("file", help="text file (one URL per line) or CSV with a url column (+ optional label)")
    ap.add_argument("--out", default="results.csv")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--mode", choices=["strict", "lenient"], default="strict")
    ap.add_argument("--base-url", default=None)
    return asyncio.run(amain(ap.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
