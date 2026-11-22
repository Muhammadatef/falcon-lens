"""Sentinel proxy client, campaign projection, STIX export and /v1/meta helpers."""

from __future__ import annotations

import base64
import binascii
import importlib.util
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from falcon_api.problem import Problem
from falcon_core.config import Settings

CAMPAIGN_TYPES = ("campaign", "kit_reuse")
SERIES_BUCKETS = 12


class SentinelClient:
    """Calls the sentinel's internal incident routes (app network only)."""

    def __init__(
        self, base_url: str, operator_key: str | None, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._http = httpx.AsyncClient(base_url=base_url, timeout=8, transport=transport, follow_redirects=False)
        self._key = operator_key

    async def close(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = await self._http.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise Problem(503, "sentinel-unavailable", "Sentinel unavailable") from exc
        if r.status_code == 404:
            raise Problem(404, "not-found", "Not found")
        if r.status_code == 409:
            raise Problem(409, "action-conflict", "Action is not awaiting a decision")
        if r.status_code == 503:
            raise Problem(503, "sentinel-unavailable", "Sentinel unavailable")
        if r.status_code >= 400:
            raise Problem(502, "sentinel-error", "Sentinel rejected the request")
        return r.json()

    async def incidents(self) -> list[dict[str, Any]]:
        data = await self._call("GET", "/internal/incidents")
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    async def incident(self, incident_id: str) -> dict[str, Any]:
        data = await self._call("GET", f"/internal/incidents/{incident_id}")
        if not isinstance(data, dict):
            raise Problem(502, "sentinel-error", "Sentinel returned an unexpected body")
        return data

    async def decide(self, incident_id: str, action_id: str, approve: bool) -> dict[str, Any]:
        verb = "approve" if approve else "reject"
        data = await self._call(
            "POST",
            f"/internal/incidents/{incident_id}/actions/{action_id}/{verb}",
            headers={"X-Operator-Key": self._key or ""},
        )
        return data if isinstance(data, dict) else {}


# ---- cursor pagination ---------------------------------------------------------------------------


def encode_cursor(updated_at: str, ident: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([updated_at, ident]).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        a, b = json.loads(raw)
        if isinstance(a, str) and isinstance(b, str):
            return a, b
    except (ValueError, binascii.Error, TypeError):
        pass
    raise Problem(422, "invalid-cursor", "Invalid cursor")


def paginate(
    items: list[dict[str, Any]], *, id_key: str, cursor: str | None, limit: int, ts_key: str = "updated_at"
) -> dict[str, Any]:
    """Newest first, stable on ties. `next_cursor` is null on the last page."""
    ordered = sorted(items, key=lambda i: (str(i.get(ts_key, "")), str(i[id_key])), reverse=True)
    if cursor:
        ts, ident = decode_cursor(cursor)
        ordered = [i for i in ordered if (str(i.get(ts_key, "")), str(i[id_key])) < (ts, ident)]
    page = ordered[:limit]
    more = len(ordered) > limit
    nxt = encode_cursor(str(page[-1].get(ts_key, "")), str(page[-1][id_key])) if more and page else None
    return {"items": page, "next_cursor": nxt}


# ---- campaigns -----------------------------------------------------------------------------------

_ADVICE = {
    "high": (
        "لا تفتح الروابط في هذه الرسائل ولا تدخل أي بيانات. بلّغ عنها عبر القناة الرسمية.",
        "Do not open links in these messages or enter any details. Report them through the official channel.",
    ),
    "default": (
        "تعامل مع الرسائل المشابهة بحذر وتحقق من المصدر عبر القنوات الرسمية.",
        "Treat similar messages with caution and confirm the sender through official channels.",
    ),
}


def _dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _series(times: list[datetime], lo: datetime, hi: datetime) -> list[int]:
    out = [0] * SERIES_BUCKETS
    span = (hi - lo).total_seconds()
    for t in times:
        idx = (
            SERIES_BUCKETS - 1
            if span <= 0
            else min(SERIES_BUCKETS - 1, int((t - lo).total_seconds() / span * SERIES_BUCKETS))
        )
        out[idx] += 1
    return out


def campaign_of(inc: dict[str, Any]) -> dict[str, Any]:
    """Project an incident onto the small campaign card the UI draws (contracts/campaign.schema.json)."""
    brand = inc.get("brand_id")
    inds = [i for i in inc.get("indicators", []) if i.get("kind") in ("domain", "url")]
    first, last = inc["created_at"], inc["updated_at"]
    times = [_dt(i["first_seen"]) for i in inds if i.get("first_seen")]
    lo, hi = (min(times), max(times)) if times else (_dt(first), _dt(last))
    sev = inc.get("severity", "low")
    ar, en = _ADVICE["high" if sev in ("high", "critical") else "default"]
    return {
        "campaign_id": "cmp_" + str(inc["incident_id"]).removeprefix("inc_"),
        "brand_id": brand,
        "title_ar": f"حملة احتيال تنتحل {brand}" if brand else "حملة احتيال مشتبه بها",
        "title_en": f"Suspected scam campaign impersonating {brand}" if brand else "Suspected scam campaign",
        "severity": sev,
        "count": max(len(inds), len(inc.get("linked_verdicts", []))),
        "first_seen": first,
        "last_seen": last,
        "series": _series(times, lo, hi),
        "advice_ar": ar,
        "advice_en": en,
        "incident_id": inc["incident_id"],
        "source": inc.get("source", "live"),
    }


def is_campaign(inc: dict[str, Any]) -> bool:
    return inc.get("type") in CAMPAIGN_TYPES


# ---- STIX ----------------------------------------------------------------------------------------

_NS = uuid.UUID("5d0c9a52-6f0e-4b86-9d0e-2f6b4a0c7a11")


def _fallback_bundle(inc: dict[str, Any]) -> dict[str, Any]:
    """Minimal STIX 2.1 bundle (identity + indicators + grouping); replaced by falcon_core.tools.stix once merged."""
    iid = inc["incident_id"]

    def sid(kind: str, *parts: str) -> str:
        return f"{kind}--{uuid.uuid5(_NS, '|'.join(parts))}"

    def ts(v: str) -> str:
        return _dt(v).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    ident = sid("identity", "falcon-lens-sentinel")
    created, modified = ts(inc["created_at"]), ts(inc["updated_at"])
    objs: list[dict[str, Any]] = [
        {
            "type": "identity",
            "spec_version": "2.1",
            "id": ident,
            "created": created,
            "modified": created,
            "name": "Falcon Lens Sentinel",
            "identity_class": "system",
        }
    ]
    refs: list[str] = []
    for ind in inc.get("indicators", []):
        val = str(ind["value_defanged"]).replace("[.]", ".").replace("\\", "\\\\").replace("'", "\\'")
        pat = {"domain": "domain-name", "url": "url", "ip": "ipv4-addr"}.get(ind["kind"])
        if pat is None:
            continue
        oid = sid("indicator", iid, ind["kind"], ind["value_defanged"])
        refs.append(oid)
        objs.append(
            {
                "type": "indicator",
                "spec_version": "2.1",
                "id": oid,
                "created_by_ref": ident,
                "created": ts(ind["first_seen"]),
                "modified": modified,
                "name": f"{ind['kind']} {ind['value_defanged']}",
                "indicator_types": ["malicious-activity"],
                "pattern": f"[{pat}:value = '{val}']",
                "pattern_type": "stix",
                "valid_from": ts(ind["first_seen"]),
                "labels": [f"falcon-incident:{iid}", f"source:{inc['source']}"],
            }
        )
    objs.append(
        {
            "type": "grouping",
            "spec_version": "2.1",
            "id": sid("grouping", iid),
            "created_by_ref": ident,
            "created": created,
            "modified": modified,
            "name": f"Falcon Lens incident {iid} ({inc['type']})",
            "context": "suspicious-activity",
            "object_refs": refs or [ident],
        }
    )
    return {"type": "bundle", "id": sid("bundle", iid, modified), "objects": objs}


def build_bundle(inc: dict[str, Any]) -> dict[str, Any]:
    try:
        from falcon_core.tools.stix import build_bundle as core_build  # type: ignore[import-not-found,unused-ignore]

        return core_build(inc)  # type: ignore[no-any-return]
    except ImportError:
        return _fallback_bundle(inc)


def merge_bundles(incidents: list[dict[str, Any]]) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for inc in incidents:
        for obj in build_bundle(inc)["objects"]:
            seen.setdefault(obj["id"], obj)
    ident = (
        f"bundle--{uuid.uuid5(_NS, '|'.join(sorted(i['incident_id'] + i['updated_at'] for i in incidents)) or 'empty')}"
    )
    return {"type": "bundle", "id": ident, "objects": list(seen.values())}


# ---- /v1/meta ------------------------------------------------------------------------------------


def scoring_bands() -> dict[str, Any] | None:
    """Read the arbiter's fitted/draft bands from params.yaml; never hard-code numbers."""
    try:
        spec = importlib.util.find_spec("falcon_core.scoring")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    p = Path(next(iter(spec.submodule_search_locations))) / "params.yaml"
    if not p.exists():
        return None
    data = yaml.safe_load(p.read_text())
    bands = data.get("bands") or {}
    if "tau_low" not in bands or "tau_high" not in bands:
        return None
    return {"tau_low": bands["tau_low"], "tau_high": bands["tau_high"], "draft": bool(data.get("draft", True))}


def meta(settings: Settings) -> dict[str, Any]:
    bands = scoring_bands()
    return {
        "thresholds": {"tau_low": bands["tau_low"], "tau_high": bands["tau_high"]} if bands else None,
        "thresholds_draft": bands["draft"] if bands else None,
        "model_ids": {
            "investigator": settings.fl_cloud_model_investigator,
            "vision": settings.fl_cloud_model_vision,
            "extractor": settings.fl_cloud_model_extractor,
            "responder": settings.fl_cloud_model_responder,
            "local": settings.fl_local_model,
        },
        "sovereign_mode": settings.fl_sovereign_mode,
        "feeds": {
            "openphish": settings.fl_feed_openphish_enabled,
            "safe_browsing": settings.google_safe_browsing_api_key is not None,
            "urlhaus": settings.urlhaus_auth_key is not None,
        },
    }
