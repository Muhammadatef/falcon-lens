"""Offline test doubles for the cascade (used by unit tests, the worker tests and replay tools).

Fixtures use only the invented brand "Falcon Demo Bank" on ``.test`` domains (CLAUDE.md).
Nothing here touches the network.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from falcon_core.cascade.models import SandboxFeatures, SandboxForm
from falcon_core.security import GuardPolicy
from falcon_core.signals.base import Evidence as SignalEvidence
from falcon_core.signals.base import SignalContext, SignalFn, SignalSpec
from falcon_core.signals.cache import MemoryCache
from falcon_core.signals.reputation.mirror import SET_KEY, UPDATED_KEY, FeedMirror, row_members

DEMO_OFFICIAL_URL = "https://falcon-demo-bank.test/"
DEMO_LOOKALIKE_URL = "https://falcon-demo-bank-login.test/secure/"
DEMO_ZERO_DAY_URL = "https://account-review-portal.test/start"
DEMO_BENIGN_URL = "https://community-garden-club.test/events"
# The SSRF guard treats ``.test`` as internal; fixture hosts are allow-listed explicitly.
FIXTURE_HOSTS = frozenset(
    [
        "falcon-demo-bank.test",
        "falcon-demo-bank-login.test",
        "account-review-portal.test",
        "community-garden-club.test",
        "synthetic-feed-entry.test",
        "plain-host.test",
        "synthetic-openphish.test",
    ]
)
FIXTURE_POLICY = GuardPolicy(allow_hosts=FIXTURE_HOSTS)
# A documentation-range-free public address (IANA example). Only returned by the stub resolver.
STUB_PUBLIC_IP = "93.184.216.34"


async def stub_resolver(host: str) -> list[str]:
    """Resolves every name to one public address (no DNS)."""
    return [STUB_PUBLIC_IP]


def phish_features(final_url: str = DEMO_LOOKALIKE_URL) -> SandboxFeatures:
    """TEST FIXTURE: a page claiming Falcon Demo Bank with a credential form."""
    return SandboxFeatures(
        redirect_chain=[final_url],
        final_url=final_url,
        title="Falcon Demo Bank | Online Banking Login",
        forms=[SandboxForm(fields=["text:username", "password"], action_origin=None)],
        visible_text=(
            "TEST FIXTURE, not a real site. Welcome to Falcon Demo Bank online banking. "
            "Sign in to Falcon Demo Bank to verify your account."
        ),
        dom_simhash="0x9f3a5c7e11223344",
        favicon_sha256="0" * 64,
    )


def official_features(final_url: str = DEMO_OFFICIAL_URL) -> SandboxFeatures:
    return SandboxFeatures(
        redirect_chain=[final_url],
        final_url=final_url,
        title="Falcon Demo Bank",
        forms=[SandboxForm(fields=["password"], action_origin=None)],
        visible_text="TEST FIXTURE, not a real site. Falcon Demo Bank official site.",
    )


def benign_features(final_url: str = DEMO_BENIGN_URL) -> SandboxFeatures:
    return SandboxFeatures(
        redirect_chain=[final_url],
        final_url=final_url,
        title="Community garden club events",
        visible_text="TEST FIXTURE, not a real site. Weekend planting schedule.",
    )


def loaded_mirror(urls: Sequence[str] = (), age_s: float = 600.0) -> FeedMirror:
    """An in-memory OpenPhish mirror (hash-only, like production) loaded ``age_s`` seconds ago.

    Built synchronously on a ``MemoryCache`` so test factories need no event loop.
    """
    kv = MemoryCache()
    members: set[str] = set()
    for u in urls:
        members.update(row_members(u))
    kv._sets[SET_KEY] = frozenset(members)  # noqa: SLF001 - test double; same layout as FeedMirror.load
    kv._data[UPDATED_KEY] = (time.time() - age_s, None)  # noqa: SLF001
    return FeedMirror(kv)


class SlowSandbox:
    """Sandbox stub that takes ``delay_s`` and counts calls (single-flight tests)."""

    def __init__(self, features: SandboxFeatures, delay_s: float = 0.2) -> None:
        self.features = features
        self.delay_s = delay_s
        self.calls = 0

    async def render(self, url: str, verdict_id: str) -> SandboxFeatures:
        self.calls += 1
        await asyncio.sleep(self.delay_s)
        return self.features


def slow_signal(
    name: str = "url.slow_probe", sleep_s: float = 1.0, timeout_ms: int = 50
) -> tuple[SignalSpec, SignalFn]:
    """A T1 signal that always overruns its timeout (degraded-path tests)."""
    spec = SignalSpec(
        name=name,
        family="url",
        tier="T1",
        input_types=("url",),
        timeout_ms=timeout_ms,
        network="egress_proxy",
        emits=(name,),
    )

    async def run(ctx: SignalContext) -> list[SignalEvidence]:
        await asyncio.sleep(sleep_s)
        return []

    return spec, run
