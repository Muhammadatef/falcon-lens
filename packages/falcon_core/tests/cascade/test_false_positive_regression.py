"""FALSE-POSITIVE REGRESSION gate plus its safety counterparts.

Popular, established legitimate sites must never be suspicious/dangerous when the address checks are clean, even
if crt.sh fails and the sandbox cannot open the page (bot blocking). The counterparts pin the fail-closed rules
(SCORING §4): no page AND no page-independent trust evidence (young or unknown domain age), a policy block, an
unknown sandbox code or the sandbox's own failure all degrade.

Uses the fitted params and the fitted T1 model, offline: network-free T1 signals, a recorded domain-age signal
and a crt.sh stand-in (the real SignalSpec, enrichment) that always errors.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from cascade_helpers import age_signal, assert_valid, make_cascade, offline_signals, run

from falcon_core.cascade import StubSandboxClient
from falcon_core.scoring.params import load_params
from falcon_core.scoring.t1_model import load_t1_model
from falcon_core.signals.base import Evidence, SignalContext
from falcon_core.signals.domain import crt

CSV = Path(__file__).resolve().parents[4] / "evals" / "datasets" / "legit_urls.csv"
OLD = 9000  # days: an established domain (> 3650)


def _refang(u: str) -> str:
    return u.replace("hxxp", "http", 1)


def _popular(n: int) -> list[str]:
    with CSV.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["category"] == "popular"]
    return [_refang(r["url"]) for r in rows[:n]]


URLS = list(dict.fromkeys([_refang("hxxps://x.com/"), _refang("hxxps://www.tripadvisor.com/"), *_popular(20)]))


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


def _cascade(sandbox: StubSandboxClient, age: tuple[object, object] | None):  # type: ignore[no-untyped-def]
    sigs = offline_signals(age)  # type: ignore[arg-type]
    sigs[crt.SPEC.name] = (crt.SPEC, _crt_down)
    cascade, _ = make_cascade(sandbox, signals=sigs, t1_model=load_t1_model(), params=load_params())
    return cascade


@pytest.mark.parametrize("url", URLS)
async def test_established_popular_site_with_crt_down_and_headless_refusal_is_not_flagged(url: str) -> None:
    cascade = _cascade(StubSandboxClient(error="http_403_empty"), age_signal(OLD))
    final = (await run(cascade, url)).docs[-1]
    assert_valid(final)
    assert final["verdict"] == "no_warning_signs", (url, final["verdict"], final["degraded_reasons"])
    assert not final["degraded"]
    if final["tier_reached"] == "T2":  # confident sites exit at T1 and never reach the sandbox
        assert any(e["signal"] == "sandbox.not_rendered" and e["weight"] == 0 for e in final["evidence"])


async def test_crt_failure_alone_never_degrades() -> None:
    cascade = _cascade(StubSandboxClient(), age_signal(OLD))
    final = (await run(cascade, _refang("hxxps://x.com/"))).docs[-1]
    assert final["verdict"] != "dangerous"
    assert not any(r.startswith("signal_error:domain.cert_age_days") for r in final.get("degraded_reasons", []))
    assert any(e["signal"] == "domain.cert_age_days" and e["error"] for e in final["evidence"])


URL = _refang("hxxps://x.com/")


@pytest.mark.parametrize(
    "age", [age_signal(3), age_signal(None, error="rdap_timeout"), age_signal(400)], ids=["young", "unknown", "mid"]
)
async def test_unrendered_page_without_established_domain_is_never_no_warning_signs(age: tuple[object, object]) -> None:
    """Cloaking path: a page that refuses us on a domain with no page-independent trust must not be cleared."""
    cascade = _cascade(StubSandboxClient(error="http_403_empty"), age)
    final = (await run(cascade, URL)).docs[-1]
    assert_valid(final)
    assert final["verdict"] != "no_warning_signs" and final["degraded"]
    assert "sandbox_unavailable:http_403_empty" in final["degraded_reasons"]


@pytest.mark.parametrize(
    "code",
    [
        "egress_blocked",
        "blocked_by_policy:private_ip",
        "blocked_by_policy",
        "http_502",
        "unreachable:ConnectError",
        "weird_new_code",
    ],
)
async def test_policy_blocks_sandbox_own_errors_and_unknown_codes_degrade_even_on_established_domains(
    code: str,
) -> None:
    cascade = _cascade(StubSandboxClient(error=code), age_signal(OLD))
    final = (await run(cascade, URL)).docs[-1]
    assert final["verdict"] != "no_warning_signs" and final["degraded"], code
