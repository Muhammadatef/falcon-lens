"""Feed health gauges: ``fl_feed_age_seconds{feed}`` and ``fl_feed_enabled{feed}``.

TODO(T-014): switch to the telemetry registry once ``falcon_core.obs`` lands. Until then this uses
``prometheus_client`` directly on the default registry, so each service's ``/metrics`` already exposes them.
"""

from __future__ import annotations

from prometheus_client import Gauge

FEED_AGE = Gauge("fl_feed_age_seconds", "Seconds since the feed mirror was last refreshed", ["feed"])
FEED_ENABLED = Gauge("fl_feed_enabled", "1 if the feed is enabled and configured, else 0", ["feed"])


def set_enabled(feed: str, enabled: bool) -> None:
    FEED_ENABLED.labels(feed=feed).set(1 if enabled else 0)


def set_age(feed: str, age_s: float) -> None:
    FEED_AGE.labels(feed=feed).set(max(0.0, age_s))
