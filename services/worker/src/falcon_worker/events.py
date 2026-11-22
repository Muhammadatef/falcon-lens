"""``verdict.created`` platform event (contracts/event.schema.json). Fingerprints, no raw text."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from falcon_core.contracts.event import PlatformEvent
from falcon_core.signals.url.textutil import defang

TOP_SIGNALS = 5


def top_signals(doc: Mapping[str, Any], n: int = TOP_SIGNALS) -> list[str]:
    """Signal names of the strongest risk evidence (by weight), unique, at most ``n``."""
    ranked = sorted(
        (e for e in doc.get("evidence", []) if e.get("weight", 0) > 0 and not e.get("error")),
        key=lambda e: -float(e.get("weight", 0)),
    )
    out: list[str] = []
    for e in ranked:
        if e["signal"] not in out:
            out.append(e["signal"])
        if len(out) >= n:
            break
    return out


def verdict_created(doc: Mapping[str, Any], meta: Mapping[str, Any]) -> dict[str, Any]:
    fp_meta = meta.get("fingerprints")
    fp = fp_meta if isinstance(fp_meta, Mapping) else {}
    reg = meta.get("final_registrable_domain") or meta.get("registrable_domain")
    brand = doc.get("impersonated_brand") or {}
    payload: dict[str, Any] = {
        "verdict": doc["verdict"],
        "risk_score": doc["risk_score"],
        "input_type": doc["input_type"],
        "registrable_domain": defang(str(reg)) if reg else None,
        "brand_id": brand.get("brand_id"),
        "fingerprints": {
            "dom_simhash": fp.get("dom_simhash"),
            "favicon_hash": fp.get("favicon_hash"),
            "script_embedding_id": None,
            "asn": None,
            "registrar": None,
            "cert_issuer": None,
            "registered_at": None,
        },
        "top_signals": top_signals(doc),
        "tier_reached": doc["tier_reached"],
        "degraded": doc["degraded"],
    }
    event = PlatformEvent(
        # Deterministic per verdict: a retried publish re-sends the same event (Sentinel dedupes on id).
        event_id="evt_" + str(doc["verdict_id"]).removeprefix("vd_"),
        type="verdict.created",
        occurred_at=datetime.now(UTC),
        source=doc.get("source", "live"),
        verdict_id=doc["verdict_id"],
        payload=payload,
    )
    return event.model_dump(mode="json")
