"""Feed health gauges: ``fl_feed_age_seconds{feed}`` and ``fl_feed_enabled{feed}``.

These are the gauges of the shared telemetry registry (``falcon_core.telemetry.metrics``), the one every
service renders on ``/metrics``. They used to be declared here on prometheus_client's default registry, which no
service exposes, so the ``FeedStale`` alert could never fire (audit 2026-11-23).
"""

from __future__ import annotations

from falcon_core.telemetry.metrics import FEED_AGE, FEED_ENABLED

__all__ = ["FEED_AGE", "FEED_ENABLED", "set_age", "set_enabled"]


def set_enabled(feed: str, enabled: bool) -> None:
    FEED_ENABLED.labels(feed=feed).set(1 if enabled else 0)


def set_age(feed: str, age_s: float) -> None:
    FEED_AGE.labels(feed=feed).set(max(0.0, age_s))
