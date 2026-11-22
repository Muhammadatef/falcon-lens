"""FALSE-POSITIVE REGRESSION gate: popular legitimate sites must never be suspicious/dangerous when the
address checks are clean, even if crt.sh fails and the sandbox cannot render (bot blocking).

Uses the fitted params and the fitted T1 model, offline: only network-free T1 signals plus a crt.sh stand-in
(the real SignalSpec, enrichment) that always errors.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from cascade_helpers import assert_valid, make_cascade, run

from falcon_core.cascade import StubSandboxClient
from falcon_core.cascade.engine import default_t1_signals
from falcon_core.scoring.params import load_params
from falcon_core.scoring.t1_model import load_t1_model
from falcon_core.signals.base import Evidence, SignalContext
from falcon_core.signals.domain import crt

CSV = Path(__file__).resolve().parents[4] / "evals" / "datasets" / "legit_urls.csv"


def _popular(n: int) -> list[str]:
    with CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == "popular"]
    return [r["url"].replace("hxxp", "http", 1) for r in rows[:n]]


URLS = ["https://x.com/", "https://www.tripadvisor.com/", *_popular(20)]


async def _crt_down(ctx: SignalContext) -> list[Evidence]:
    return [
        Evidence(
            signal=crt.SPEC.name,
            family="domain",
            observed=None,
            polarity="neutral",
            tier="T1",
            confidence=0.0,
            error="HTTPStatusError: 502",
        )
    ]


def _signals() -> dict[str, tuple[object, object]]:
    sigs: dict[str, tuple[object, object]] = {n: v for n, v in default_t1_signals().items() if v[0].network == "none"}
    sigs[crt.SPEC.name] = (crt.SPEC, _crt_down)
    return sigs


@pytest.mark.parametrize("url", URLS)
async def test_popular_site_with_crt_down_and_bot_blocked_sandbox_is_not_flagged(url: str) -> None:
    cascade, _ = make_cascade(
        StubSandboxClient(error="render_failed"),
        signals=_signals(),  # type: ignore[arg-type]
        t1_model=load_t1_model(),
        params=load_params(),
    )
    final = (await run(cascade, url)).docs[-1]
    assert_valid(final)
    assert final["verdict"] == "no_warning_signs", (url, final["verdict"], final["degraded_reasons"])
    assert not final["degraded"]


async def test_crt_failure_alone_never_degrades() -> None:
    cascade, _ = make_cascade(
        StubSandboxClient(),
        signals=_signals(),  # type: ignore[arg-type]
        t1_model=load_t1_model(),
        params=load_params(),
    )
    final = (await run(cascade, "https://x.com/")).docs[-1]
    assert final["verdict"] != "dangerous"
    assert not any(r.startswith("signal_error:domain.cert_age_days") for r in final.get("degraded_reasons", []))
    assert any(e["signal"] == "domain.cert_age_days" and e["error"] for e in final["evidence"])
