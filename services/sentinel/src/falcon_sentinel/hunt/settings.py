"""Hunt runtime settings from the environment (HUNTER.md section 5). Defaults are the safe ones."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# crt.sh publishes no terms of use (checked 2026-11-24, DECISIONS.md), so ct_lookup is NOT on by default:
# it runs only when an operator lists it in FL_HUNT_SOURCES.
DEFAULT_SOURCES = ("permutation",)
KNOWN_SOURCES = frozenset({"permutation", "ct_lookup", "ct_search", "fixture", "search", "ads", "maps"})
NETWORK_SOURCES = frozenset({"permutation", "ct_lookup", "ct_search"})  # permutation needs DoH


def _bool(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def _int(env: Mapping[str, str], name: str, default: int, lo: int = 0) -> int:
    try:
        return max(lo, int(env.get(name, default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class HuntSettings:
    enabled: bool = False
    sources: tuple[str, ...] = DEFAULT_SOURCES
    interval_min: int = 15
    ct_min_interval_s: int = 120
    dns_qps: int = 5
    dns_max_per_cycle: int = 1500
    submit_max_per_hour: int = 20
    submit_max_per_day: int = 200
    prescore_min: int = 60
    proxy: str | None = "http://hunt-egress:3128"
    api_url: str = "http://api:8000"
    api_key: str | None = None
    doh_url: str = "https://dns.google/resolve"
    fixture_path: str | None = None
    offline: bool = False  # FL_SOVEREIGN_MODE=1 with FL_OFFLINE_LOOKUPS=true: every network source is off
    jobs_lag_max: int = 20
    recheck_hours: int = 24

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> HuntSettings:
        e = os.environ if env is None else env
        raw = e.get("FL_HUNT_SOURCES")
        srcs = tuple(s.strip() for s in raw.split(",") if s.strip()) if raw is not None else DEFAULT_SOURCES
        unknown = [s for s in srcs if s not in KNOWN_SOURCES]
        if unknown:
            raise ValueError(f"FL_HUNT_SOURCES: unknown {unknown}")
        offline = _bool(e.get("FL_SOVEREIGN_MODE")) and _bool(e.get("FL_OFFLINE_LOOKUPS"))
        return cls(
            enabled=_bool(e.get("FL_HUNT_ENABLED")),
            sources=srcs,
            interval_min=_int(e, "FL_HUNT_INTERVAL_MIN", 15, 1),
            ct_min_interval_s=_int(e, "FL_HUNT_CT_MIN_INTERVAL_S", 120, 120),  # never below 120 s
            dns_qps=_int(e, "FL_HUNT_DNS_QPS", 5, 1),
            dns_max_per_cycle=_int(e, "FL_HUNT_DNS_MAX_PER_CYCLE", 1500),
            submit_max_per_hour=_int(e, "FL_HUNT_SUBMIT_MAX_PER_HOUR", 20),
            submit_max_per_day=_int(e, "FL_HUNT_SUBMIT_MAX_PER_DAY", 200),
            prescore_min=_int(e, "FL_HUNT_PRESCORE_MIN", 60),
            proxy=e.get("FL_HUNT_PROXY", "http://hunt-egress:3128") or None,
            api_url=e.get("FL_HUNT_API_URL") or e.get("FL_API_URL") or "http://api:8000",
            api_key=e.get("FL_HUNT_API_KEY") or None,
            doh_url=e.get("FL_HUNT_DOH_URL", "https://dns.google/resolve"),
            fixture_path=e.get("FL_HUNT_FIXTURE") or None,
            offline=offline,
        )

    def active_sources(self) -> tuple[str, ...]:
        return tuple(s for s in self.sources if not (self.offline and s in NETWORK_SOURCES))
