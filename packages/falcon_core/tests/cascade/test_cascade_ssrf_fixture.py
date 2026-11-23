"""SSRF pre-check vs fixture hosts the worker cannot resolve (they live on the sandbox network)."""

from __future__ import annotations

from cascade_helpers import make_cascade, run

from falcon_core.cascade import StubSandboxClient
from falcon_core.cascade.testing import benign_features
from falcon_core.security import GuardPolicy


async def _nxdomain(host: str) -> list[str]:
    raise OSError("no such host")


async def test_allow_listed_fixture_host_with_dns_failure_is_still_rendered() -> None:
    sandbox = StubSandboxClient(default=benign_features("http://fixtures/official/"))
    cascade, m = make_cascade(
        sandbox, guard_policy=GuardPolicy(allow_hosts=frozenset({"fixtures"})), resolver=_nxdomain
    )
    final = (await run(cascade, "http://fixtures/official/")).docs[-1]
    assert sandbox.calls, "allow-listed fixture host must reach the sandbox"
    assert not any(r.startswith("not_rendered") for r in final.get("degraded_reasons", []))


async def test_unlisted_host_with_dns_failure_is_blocked() -> None:
    sandbox = StubSandboxClient(default=benign_features())
    cascade, _ = make_cascade(sandbox, guard_policy=GuardPolicy(), resolver=_nxdomain)
    final = (await run(cascade, "https://unresolvable-host.test/")).docs[-1]
    assert sandbox.calls == []
    assert final["degraded"] and final["verdict"] != "no_warning_signs"


async def _hang(host: str) -> list[str]:
    import asyncio

    await asyncio.sleep(5)
    return []


async def test_allow_listed_fixture_host_with_dns_timeout_is_not_blocked() -> None:
    sandbox = StubSandboxClient(default=benign_features("http://community-garden-club.test/"))
    cascade, _ = make_cascade(
        sandbox,
        guard_policy=GuardPolicy(allow_hosts=frozenset({"community-garden-club.test"})),
        resolver=_hang,
        ssrf_timeout_s=0.05,
    )
    final = (await run(cascade, "http://community-garden-club.test/")).docs[-1]
    assert sandbox.calls
    assert not any(r.startswith("not_rendered") for r in final.get("degraded_reasons", []))


async def test_clean_host_that_does_not_resolve_is_not_degraded_but_noted() -> None:
    from falcon_core.cascade.engine import default_t1_signals
    from falcon_core.scoring.params import load_params
    from falcon_core.scoring.t1_model import load_t1_model

    offline = {n: v for n, v in default_t1_signals().items() if v[0].network == "none"}
    cascade, _ = make_cascade(
        StubSandboxClient(default=benign_features()),
        signals=offline,
        guard_policy=GuardPolicy(),
        resolver=_nxdomain,
        t1_model=load_t1_model(),
        params=load_params(),
    )
    final = (await run(cascade, "hxxps://www.mayoclinic.org/".replace("hxxp", "http", 1))).docs[-1]
    assert final["verdict"] == "no_warning_signs" and not final["degraded"]
    assert any(e["signal"] == "sandbox.not_rendered" and e["weight"] == 0 for e in final["evidence"])
