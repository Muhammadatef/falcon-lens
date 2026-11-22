"""Minimal STIX 2.1 bundle builder for incident export.

Fields checked against the OASIS STIX 2.1 spec (docs.oasis-open.org/cti/stix/v2.1/os, fetched 2026-11-22):
- common SDO properties: type, spec_version="2.1", id=<type>--<uuid>, created, modified
- Indicator requires pattern, pattern_type ("stix"), valid_from
- Grouping requires context (open vocab, e.g. "suspicious-activity") and object_refs
- Bundle requires type="bundle" and id; it has no spec_version in 2.1
Object ids are UUIDv5 over stable inputs so re-exporting the same incident gives the same ids.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

_NS = uuid.UUID("5d0c9a52-6f0e-4b86-9d0e-2f6b4a0c7a11")  # project namespace for deterministic ids


def _id(kind: str, *parts: str) -> str:
    return f"{kind}--{uuid.uuid5(_NS, '|'.join(parts))}"


def _ts(value: str) -> str:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    dt = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace("'", "\\'")


def _pattern(kind: str, value: str) -> str | None:
    refanged = value.replace("[.]", ".")
    if kind == "domain":
        return f"[domain-name:value = '{_esc(refanged)}']"
    if kind == "url":
        return f"[url:value = '{_esc(refanged)}']"
    if kind == "ip":
        kind = "ipv6-addr" if ":" in refanged else "ipv4-addr"
        return f"[{kind}:value = '{_esc(refanged)}']"
    return None  # dom_hash / script_cluster are Falcon-internal fingerprints: not STIX observables


def build_bundle(incident: dict[str, Any]) -> dict[str, Any]:
    iid = incident["incident_id"]
    created = _ts(incident["created_at"])
    modified = _ts(incident["updated_at"])
    identity_id = _id("identity", "falcon-lens-sentinel")
    objects: list[dict[str, Any]] = [
        {
            "type": "identity",
            "spec_version": "2.1",
            "id": identity_id,
            "created": created,
            "modified": created,
            "name": "Falcon Lens Sentinel",
            "identity_class": "system",
        }
    ]
    refs: list[str] = []
    for ind in incident["indicators"]:
        pat = _pattern(ind["kind"], ind["value_defanged"])
        if pat is None:
            continue
        oid = _id("indicator", iid, ind["kind"], ind["value_defanged"])
        refs.append(oid)
        objects.append(
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": oid,
                "created_by_ref": identity_id,
                "created": _ts(ind["first_seen"]),
                "modified": modified,
                "name": f"{ind['kind']} {ind['value_defanged']}",
                "indicator_types": ["malicious-activity"],
                "pattern": pat,
                "pattern_type": "stix",
                "valid_from": _ts(ind["first_seen"]),
                "labels": [f"falcon-incident:{iid}", f"source:{incident['source']}"],
            }
        )
    objects.append(
        {
            "type": "grouping",
            "spec_version": "2.1",
            "id": _id("grouping", iid),
            "created_by_ref": identity_id,
            "created": created,
            "modified": modified,
            "name": f"Falcon Lens incident {iid} ({incident['type']})",
            "context": "suspicious-activity",
            "object_refs": refs or [identity_id],
        }
    )
    return {"type": "bundle", "id": _id("bundle", iid, modified), "objects": objects}
