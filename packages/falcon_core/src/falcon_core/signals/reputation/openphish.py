"""rep.openphish: exact-URL / host match against the private OpenPhish mirror (``ctx.mirror``).

``observed.feed_age_s`` and ``observed.fresh`` (age < 6 h) let the arbiter apply H2 only on a fresh mirror.
No URL is logged or emitted; only a short hash prefix identifies the lookup.
"""

from __future__ import annotations

import hashlib

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, async_signal
from falcon_core.signals.cache import default_cache, get_clock
from falcon_core.signals.domain.common import error_evidence
from falcon_core.signals.reputation import metrics
from falcon_core.signals.reputation.mirror import (
    FEED,
    FRESH_MAX_AGE_S,
    FeedMirror,
    feed_enabled_openphish,
    simple_canon,
)

SPEC = SignalSpec(
    name="rep.openphish",
    family="reputation",
    tier="T0",
    input_types=("url",),
    timeout_ms=300,
    network="local_mirror",
    emits=("rep.openphish",),
)


def _mirror(ctx: SignalContext) -> FeedMirror:
    m = getattr(ctx, "mirror", None)
    return m if isinstance(m, FeedMirror) else FeedMirror(default_cache())


@async_signal(SPEC)
async def run(ctx: SignalContext) -> list[Evidence]:
    enabled = feed_enabled_openphish()
    metrics.set_enabled(FEED, enabled)
    if not enabled:
        return [error_evidence(SPEC, "feed_disabled", FEED)]
    if not ctx.url:
        return []
    hit = await _mirror(ctx).lookup(ctx.url)
    if hit.updated_at is None:
        return [error_evidence(SPEC, "feed_unavailable", FEED)]
    age = max(0, int(get_clock(ctx)() - hit.updated_at))
    metrics.set_age(FEED, age)
    fresh = age < FRESH_MAX_AGE_S
    sc = simple_canon(ctx.url) or ""
    ref = hashlib.sha256(sc.encode()).hexdigest()[:16]
    if hit.match is None:
        return [
            Evidence(
                signal=SPEC.name,
                family="reputation",
                observed={"hit": False, "feed": FEED, "feed_age_s": age, "fresh": fresh},
                display={
                    "en": "Not listed in the OpenPhish feed mirror",
                    "ar": "غير مدرج في نسخة قائمة OpenPhish",
                },
                polarity="neutral",
                source=FEED,
                tier="T0",
            )
        ]
    return [
        Evidence(
            signal=SPEC.name,
            family="reputation",
            observed={
                "hit": True,
                "match": hit.match,
                "feed": FEED,
                "feed_age_s": age,
                "fresh": fresh,
                "url_ref": ref,
            },
            display={
                "en": "Listed in the OpenPhish phishing feed" + ("" if fresh else " (feed is stale)"),
                "ar": "مدرج في قائمة OpenPhish للتصيّد" + ("" if fresh else " (القائمة قديمة)"),
            },
            polarity="risk",
            source=FEED,
            tier="T0",
        )
    ]
