"""Unit tests for scripts/batch_check.py against a fake API (httpx.MockTransport). Fixtures use .test hosts only."""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

import batch_check as bc
import httpx

A, B, C, D = (f"http://{n}.test/" for n in ("a", "b", "c", "d"))
Handler = Callable[[httpx.Request], httpx.Response]


def doc(verdict: str, score: int = 50, vid: str = "vd_X", final: bool = True, **kw: Any) -> dict[str, Any]:
    return {
        "verdict_id": vid,
        "verdict": verdict,
        "risk_score": score,
        "final": final,
        "degraded": False,
        "tier_reached": "T1",
        "latency_ms": 12,
        "evidence": [
            {"id": "ev_aaaaaaaa", "signal": "url.homograph", "weight": 9, "polarity": "risk"},
            {"id": "ev_bbbbbbbb", "signal": "rep.feed", "weight": 30, "polarity": "risk", "hard_rule": "H2"},
        ],
        "reasons": [{"ar": "x", "en": "y", "evidence_ids": ["ev_aaaaaaaa"]}],
        **kw,
    }


def client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="http://api.test", transport=httpx.MockTransport(handler))


async def nosleep(_: float) -> None:
    return None


def test_binary_mapping() -> None:
    assert bc.binary_label("dangerous", "strict") == "fraud"
    assert bc.binary_label("suspicious", "strict") == "fraud"
    assert bc.binary_label("suspicious", "lenient") == "legit"
    assert bc.binary_label("no_warning_signs", "strict") == "legit"
    assert bc.binary_label("could_not_check", "strict") == "fraud"
    assert bc.binary_label("could_not_check", "lenient") == "legit"


def test_parse_input_txt_and_csv() -> None:
    assert bc.parse_input("# c\n\nhttp://a.test/\n  http://b.test/ \n") == [
        ("http://a.test/", None),
        ("http://b.test/", None),
    ]
    got = bc.parse_input("id,URL,Label\n1,http://a.test/,Fraud\n2,http://b.test/,legit\n3,http://c.test/,\n")
    assert got == [("http://a.test/", "fraud"), ("http://b.test/", "legit"), ("http://c.test/", None)]


def test_row_mapping_and_top_reasons() -> None:
    row = bc.row_from_verdict(A, doc("suspicious", 61, degraded=True, degraded_reasons=["t2_timeout"]), "strict", 5)
    assert row["verdict"] == "suspicious" and row["binary_label"] == "fraud" and row["risk_score"] == "61"
    assert row["degraded"] == "true" and row["degraded_reasons"] == "t2_timeout"
    assert row["top_reasons"] == "url.homograph;H2" and row["tier_reached"] == "T1"
    assert bc.row_from_verdict(A, doc("suspicious"), "lenient", 5)["binary_label"] == "legit"


def test_wilson_and_metrics() -> None:
    lo, hi = bc.wilson(8, 10)
    assert 0.49 < lo < 0.50 and 0.94 < hi < 0.95
    assert bc.wilson(0, 0) == (0.0, 1.0)
    pairs = [("fraud", "fraud")] * 3 + [("fraud", "legit"), ("legit", "fraud"), ("legit", "legit")]
    m = bc.metrics(pairs)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (3, 1, 1, 1)
    assert m["precision"]["value"] == 0.75 and m["recall"]["value"] == 0.75 and m["fpr"]["value"] == 0.5


def test_check_one_polls_until_final_and_marks_rejections() -> None:
    polls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            if "bad.test" in req.read().decode():
                return httpx.Response(422, json={})
            return httpx.Response(202, json=doc("suspicious", vid="vd_1", final=False))
        polls["n"] += 1
        return httpx.Response(200, json=doc("dangerous", 90, vid="vd_1", final=polls["n"] >= 2))

    async def go() -> tuple[dict[str, str], dict[str, str]]:
        async with client(handler) as c:
            ok = await bc.check_one(c, A, "strict", sleep=nosleep)
            return ok, await bc.check_one(c, "http://bad.test/", "strict", sleep=nosleep)

    ok, bad = asyncio.run(go())
    assert ok["verdict"] == "dangerous" and polls["n"] == 2
    assert bad["verdict"] == "could_not_check" and bad["binary_label"] == "fraud" and "422" in bad["error"]


def test_429_backoff_honours_retry_after() -> None:
    calls = {"n": 0}
    waits: list[float] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, headers={"Retry-After": "3"})
        return httpx.Response(200, json=doc("no_warning_signs", 4))

    async def sleep(s: float) -> None:
        waits.append(s)

    async def go() -> dict[str, str]:
        async with client(handler) as c:
            return await bc.check_one(c, A, "strict", sleep=sleep)

    row = asyncio.run(go())
    assert row["verdict"] == "no_warning_signs" and waits == [3.0, 3.0]


def test_429_gives_up_as_could_not_check() -> None:
    async def go() -> dict[str, str]:
        async with client(lambda r: httpx.Response(429)) as c:
            return await bc.check_one(c, A, "strict", sleep=nosleep)

    assert "429" in asyncio.run(go())["error"]


def test_timeout_without_final_is_could_not_check() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json=doc("suspicious", vid="vd_9", final=False))

    async def go() -> dict[str, str]:
        async with client(handler) as c:
            return await bc.check_one(c, A, "strict", sleep=nosleep, final_timeout=-1)

    assert asyncio.run(go())["error"] == "no final verdict in time"


def test_resume_skips_answered_rows_and_retries_failed(tmp_path: Path) -> None:
    out = tmp_path / "r.csv"
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        url = req.read().decode()
        seen.append(url)
        if "b.test" in url and len(seen) < 3:
            return httpx.Response(500)
        return httpx.Response(200, json=doc("dangerous", 88, vid=f"vd_{len(seen)}"))

    async def go(mode: str) -> list[dict[str, str]]:
        async with client(handler) as c:
            rows, _ = await bc.run_batch(c, [(A, "fraud"), (B, "legit"), (A, None)], out, mode, 2, sleep=nosleep)
            return rows

    first = asyncio.run(go("strict"))
    assert [r["url"] for r in first] == [A, B]  # duplicate dropped, input order kept
    assert first[1]["verdict"] == "could_not_check"
    n_first = len(seen)
    second = asyncio.run(go("lenient"))
    assert len(seen) == n_first + 1 and B in seen[-1]  # only the failed one was re-submitted
    assert [r["verdict"] for r in second] == ["dangerous", "dangerous"]
    with out.open(newline="") as f:
        assert [r["url"] for r in csv.DictReader(f)] == [A, B]


def test_summary_reports_both_modes_and_unchecked() -> None:
    rows = [
        bc.row_from_verdict(A, doc("dangerous"), "strict", 1),
        bc.row_from_verdict(B, doc("suspicious"), "strict", 1),
        bc.row_from_verdict(C, doc("no_warning_signs"), "strict", 1),
        bc.row_unchecked(D, "x", "strict"),
    ]
    text = bc.summarise(rows, {A: "fraud", B: "legit", C: "legit", D: "fraud"})
    assert "strict mode" in text and "lenient mode" in text and "could_not_check: 1" in text
    assert "excluding 1 could_not_check" in text
    assert "Metrics" not in bc.summarise(rows, {})


def test_resolve_key_prefers_env_then_file(tmp_path: Path) -> None:
    f = tmp_path / ".env"
    f.write_text("FL_WEB_READ_KEY='from-file'\n")
    assert bc.resolve_key({}, f) == "from-file"
    assert bc.resolve_key({"FL_BATCH_API_KEY": "from-env"}, f) == "from-env"
    assert bc.resolve_key({}, tmp_path / "none") is None
