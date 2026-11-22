"""Synthetic event builders for rule tests. Invented .test domains and brand only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sentinel_core.events import Event, parse_event
from sentinel_core.ids import make_ulid

T0 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
_n = 0


def ev(
    type_: str,
    minutes: float,
    payload: dict[str, Any],
    key: str,
    source: str = "replay",
    vid: str | None = None,
) -> Event:
    at = T0 + timedelta(minutes=minutes)
    return parse_event(
        {
            "schema_version": "1.0",
            "event_id": f"evt_{make_ulid(at, key)}",
            "type": type_,
            "occurred_at": at.isoformat().replace("+00:00", "Z"),
            "source": source,
            "verdict_id": vid,
            "payload": payload,
        }
    )


def verdict_ev(
    domain: str,
    minutes: float,
    verdict: str = "dangerous",
    brand: str | None = None,
    simhash: int | None = None,
    type_: str = "verdict.created",
    key: str | None = None,
) -> Event:
    fp: dict[str, Any] = {
        "asn": "AS64500",
        "registrar": "Example Registrar",
        "cert_issuer": "Example CA",
    }
    if simhash is not None:
        fp["dom_simhash"] = f"{simhash:016x}"
    k = key or f"v|{domain}|{minutes}|{type_}"
    return ev(
        type_,
        minutes,
        {
            "verdict": verdict,
            "risk_score": 90,
            "input_type": "url",
            "registrable_domain": domain,
            "brand_id": brand,
            "fingerprints": fp,
            "top_signals": [],
        },
        k,
        vid="vrd_" + hashlib.md5(k.encode()).hexdigest()[:8],
    )


def observed_ev(domain: str, minutes: float, brand: str | None = "falcon_demo_bank") -> Event:
    return ev(
        "domain.observed",
        minutes,
        {
            "domain_defanged": domain.replace(".", "[.]"),
            "brand_candidates": [brand] if brand else [],
            "first_seen": "2026-11-20T08:00:00Z",
            "source": "fixture",
        },
        f"o|{domain}|{minutes}",
    )


def report_ev(fp: str, minutes: float, i: int = 0) -> Event:
    return ev(
        "report.submitted",
        minutes,
        {"kind": "scam_link", "script_fingerprint": fp},
        f"r|{fp}|{minutes}|{i}",
    )


def feedback_ev(signal: str, minutes: float, i: int = 0, kind: str = "false_positive") -> Event:
    return ev(
        "feedback.submitted",
        minutes,
        {"kind": kind, "signal": signal},
        f"f|{signal}|{minutes}|{i}|{kind}",
    )
