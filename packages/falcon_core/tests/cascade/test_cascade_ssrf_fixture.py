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
