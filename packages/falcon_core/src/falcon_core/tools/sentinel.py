"""Sentinel tools (contracts/tools.schema.json `sentinel_tools`).

read          : search_verdicts, find_related_domains, get_past_incidents, feed_status
internal_auto : requeue_check, block_indicator, upsert_incident, raise_alert, update_campaign_board, export_stix
external_draft: draft_takedown, draft_police_report  (produce a draft only; this module never sends anything)

Every internal_auto / external_draft execution is appended to the append-only audit_log with its evidence ids.
Indicator-bearing arguments obey the provenance rule: they must be an indicator of the named incident.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .stix import build_bundle

JOBS_STREAM = "fl:jobs"
BOARD_STREAM = "fl:board"
BLOCK_PREFIX = "fl:block:"

READ_TOOLS = ("search_verdicts", "find_related_domains", "get_past_incidents", "feed_status")
INTERNAL_TOOLS = (
    "requeue_check",
    "block_indicator",
    "upsert_incident",
    "raise_alert",
    "update_campaign_board",
    "export_stix",
)
DRAFT_TOOLS = ("draft_takedown", "draft_police_report")
TOOL_MODE: dict[str, str] = {
    **dict.fromkeys(READ_TOOLS, "read"),
    **dict.fromkeys(INTERNAL_TOOLS, "internal_auto"),
    **dict.fromkeys(DRAFT_TOOLS, "external_draft"),
}


class ToolError(Exception):
    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchVerdictsArgs(Strict):
    brand_id: str | None = None
    registrable_domain: str | None = None
    since: datetime | None = None
    limit: int = Field(50, ge=1, le=200)


class FindRelatedArgs(Strict):
    incident_id: str
    keys: list[Literal["dom_simhash", "asn", "registrar", "cert_issuer"]] = Field(min_length=1)


class PastIncidentsArgs(Strict):
    brand_id: str | None = None
    type: str | None = None
    limit: int = Field(10, ge=1, le=20)


class NoArgs(Strict):
    pass


class RequeueArgs(Strict):
    url: str


class BlockArgs(Strict):
    indicator: str
    ttl_hours: int = Field(ge=1, le=168)


class UpsertArgs(Strict):
    incident_id: str
    patch: dict[str, Any]


class RaiseAlertArgs(Strict):
    incident_id: str
    severity: Literal["low", "medium", "high", "critical"]


class IncidentOnlyArgs(Strict):
    incident_id: str


class TakedownArgs(Strict):
    incident_id: str
    recipient_kind: Literal["registrar", "host"]


ARG_MODELS: dict[str, type[Strict]] = {
    "search_verdicts": SearchVerdictsArgs,
    "find_related_domains": FindRelatedArgs,
    "get_past_incidents": PastIncidentsArgs,
    "feed_status": NoArgs,
    "requeue_check": RequeueArgs,
    "block_indicator": BlockArgs,
    "upsert_incident": UpsertArgs,
    "raise_alert": RaiseAlertArgs,
    "update_campaign_board": IncidentOnlyArgs,
    "export_stix": IncidentOnlyArgs,
    "draft_takedown": TakedownArgs,
    "draft_police_report": IncidentOnlyArgs,
}
UPSERT_PATCH_KEYS = frozenset({"severity", "severity_reason", "summary", "status"})


class IncidentAccess(Protocol):
    def get(self, incident_id: str) -> dict[str, Any] | None: ...
    def all(self) -> list[dict[str, Any]]: ...
    def update(self, incident_id: str, fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]: ...
    async def flush(self) -> Any: ...


class ToolRepo(Protocol):
    async def audit_append(self, entry: dict[str, Any]) -> int: ...
    async def block_put(self, block: dict[str, Any]) -> None: ...
    async def block_get(self, action_id: str) -> dict[str, Any] | None: ...
    async def block_revert(self, action_id: str, at: datetime) -> None: ...
    async def query_features(self, since: datetime | None, limit: int) -> list[dict[str, Any]]: ...


class RedisPort(Protocol):
    async def xadd(self, name: str, fields: dict[str, str], **kw: Any) -> Any: ...
    async def set(self, name: str, value: str, **kw: Any) -> Any: ...
    async def delete(self, *names: str) -> Any: ...


class MetricsPort(Protocol):
    def action(self, tool: str, mode: str) -> None: ...
    def block_reverted(self) -> None: ...


class NullMetrics:
    def action(self, tool: str, mode: str) -> None:
        return None

    def block_reverted(self) -> None:
        return None


@dataclass
class ToolContext:
    incidents: IncidentAccess
    repo: ToolRepo
    redis: RedisPort
    http: httpx.AsyncClient | None = None
    alertmanager_url: str | None = None
    metrics: MetricsPort = field(default_factory=NullMetrics)
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


@dataclass
class ToolResult:
    ok: bool
    status: str  # executed | awaiting_approval | failed | read
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def refang(v: str) -> str:
    return v.strip().lower().replace("[.]", ".")


def action_id_for(incident_id: str, tool: str, args: dict[str, Any]) -> str:
    h = hashlib.sha256(
        f"{incident_id}|{tool}|{json.dumps(args, sort_keys=True)}".encode()
    ).hexdigest()
    return f"act_{h[:24]}"


def validate_args(tool: str, args: dict[str, Any]) -> Strict:
    model = ARG_MODELS.get(tool)
    if model is None:
        raise ToolError("unknown_tool", tool)
    try:
        parsed = model(**args)
    except ValidationError as exc:
        raise ToolError("bad_args", str(exc.errors()[0]["msg"])) from exc
    if isinstance(parsed, UpsertArgs) and not set(parsed.patch) <= UPSERT_PATCH_KEYS:
        raise ToolError("bad_args", "patch keys limited to severity|severity_reason|summary|status")
    return parsed


def find_indicator(incident: dict[str, Any], value: str) -> dict[str, Any]:
    """Provenance: the value must be (the refanged form of) an indicator of this incident."""
    want = refang(value)
    for ind in incident["indicators"]:
        if refang(ind["value_defanged"]) == want:
            return dict(ind)
    raise ToolError("provenance", "indicator is not part of the incident")


def _inc(ctx: ToolContext, incident_id: str) -> dict[str, Any]:
    inc = ctx.incidents.get(incident_id)
    if inc is None:
        raise ToolError("not_found", incident_id)
    return inc


# ---------------------------------------------------------------- read tools


async def _search_verdicts(ctx: ToolContext, a: SearchVerdictsArgs) -> dict[str, Any]:
    rows = await ctx.repo.query_features(a.since, 5000)
    out = []
    for ev in rows:
        if not str(ev["type"]).startswith("verdict."):
            continue
        p = ev["payload"]
        if a.brand_id and p.get("brand_id") != a.brand_id:
            continue
        if a.registrable_domain and p.get("registrable_domain") != a.registrable_domain:
            continue
        out.append(
            {
                "verdict_id": ev.get("verdict_id"),
                "event_id": ev["event_id"],
                "verdict": p.get("verdict"),
                "domain": str(p.get("registrable_domain", "")).replace(".", "[.]"),
                "at": ev["occurred_at"],
            }
        )
        if len(out) >= a.limit:
            break
    return {"verdicts": out}


async def _find_related(ctx: ToolContext, a: FindRelatedArgs) -> dict[str, Any]:
    inc = _inc(ctx, a.incident_id)
    own = {e["event_id"] for e in inc["timeline"] if "event_id" in e}
    keys = inc.get("correlation_keys", {})
    rows = await ctx.repo.query_features(None, 5000)
    related: dict[str, set[str]] = {}
    for ev in rows:
        if ev["event_id"] in own:
            continue
        fp = (ev["payload"].get("fingerprints") or {}) if isinstance(ev["payload"], dict) else {}
        dom = ev["payload"].get("registrable_domain")
        if not dom:
            continue
        for k in a.keys:
            v = fp.get(k)
            if k == "dom_simhash":
                mine = [int(x, 16) for x in keys.get("dom_simhash", [])]
                try:
                    hit = v is not None and any(
                        (int(str(v), 16) ^ m).bit_count() <= 6 for m in mine
                    )
                except ValueError:
                    hit = False
            else:
                hit = v is not None and str(v) in [str(x) for x in keys.get(k, [])]
            if hit:
                related.setdefault(str(dom).replace(".", "[.]"), set()).add(k)
    return {"related": [{"domain": d, "matched_on": sorted(k)} for d, k in sorted(related.items())]}


async def _past_incidents(ctx: ToolContext, a: PastIncidentsArgs) -> dict[str, Any]:
    rows = [
        i
        for i in ctx.incidents.all()
        if (not a.brand_id or i.get("brand_id") == a.brand_id)
        and (not a.type or i["type"] == a.type)
    ]
    rows.sort(key=lambda i: i["created_at"], reverse=True)
    return {
        "incidents": [
            {k: i[k] for k in ("incident_id", "type", "severity", "status", "created_at")}
            for i in rows[: a.limit]
        ]
    }


async def _feed_status(ctx: ToolContext, a: NoArgs) -> dict[str, Any]:
    latest: dict[str, dict[str, Any]] = {}
    for ev in await ctx.repo.query_features(None, 5000):
        if ev["type"] == "feed.updated":
            p = ev["payload"]
            cur = latest.get(str(p.get("feed")))
            if cur is None or ev["occurred_at"] > cur["at"]:
                latest[str(p.get("feed"))] = {
                    "at": ev["occurred_at"],
                    "entries": p.get("entries"),
                    "age_s": p.get("age_s"),
                }
    return {"feeds": latest}


# ---------------------------------------------------------------- internal_auto


async def _requeue(ctx: ToolContext, incident_id: str, a: RequeueArgs) -> dict[str, Any]:
    ind = find_indicator(_inc(ctx, incident_id), a.url)
    await ctx.redis.xadd(
        JOBS_STREAM,
        {
            "data": json.dumps(
                {
                    "kind": "requeue_check",
                    "indicator": refang(ind["value_defanged"]),
                    "indicator_kind": ind["kind"],
                    "incident_id": incident_id,
                }
            )
        },
        maxlen=10000,
        approximate=True,
    )
    return {"queued": ind["value_defanged"]}


async def _block(
    ctx: ToolContext, incident_id: str, action_id: str, a: BlockArgs
) -> dict[str, Any]:
    ind = find_indicator(_inc(ctx, incident_id), a.indicator)
    now = ctx.now()
    until = now + timedelta(hours=a.ttl_hours)
    key = f"{BLOCK_PREFIX}{ind['kind']}:{ind['sha256']}"
    await ctx.redis.set(key, action_id, ex=a.ttl_hours * 3600)
    await ctx.repo.block_put(
        {
            "action_id": action_id,
            "incident_id": incident_id,
            "kind": ind["kind"],
            "value_defanged": ind["value_defanged"],
            "sha256": ind["sha256"],
            "redis_key": key,
            "blocked_at": now,
            "expires_at": until,
        }
    )

    def mark(inc: dict[str, Any]) -> None:
        for i in inc["indicators"]:
            if i["kind"] == ind["kind"] and i["value_defanged"] == ind["value_defanged"]:
                i["blocked_until"] = iso(until)

    ctx.incidents.update(incident_id, mark)
    return {"blocked": ind["value_defanged"], "until": iso(until), "key": key}


async def unblock(ctx: ToolContext, action_id: str, operator: str) -> dict[str, Any]:
    """`make unblock ID=<action_id>`: delete the Redis key, mark the block reverted, audit, count."""
    blk = await ctx.repo.block_get(action_id)
    if blk is None:
        raise ToolError("not_found", f"no block for {action_id}")
    if blk.get("reverted_at"):
        return {"already_reverted": True}
    now = ctx.now()
    await ctx.redis.delete(blk["redis_key"])
    await ctx.repo.block_revert(action_id, now)
    iid = blk["incident_id"]
    if ctx.incidents.get(iid) is not None:

        def mark(inc: dict[str, Any]) -> None:
            for a in inc["actions"]:
                if a["action_id"] == action_id:
                    a["status"] = "reverted"
                    a["at"] = iso(now)
            for i in inc["indicators"]:
                if i["kind"] == blk["kind"] and i["value_defanged"] == blk["value_defanged"]:
                    i["blocked_until"] = None

        ctx.incidents.update(iid, mark)
        await ctx.incidents.flush()
    await ctx.repo.audit_append(
        {
            "at": now,
            "actor": operator,
            "incident_id": iid,
            "action_id": action_id,
            "tool": "unblock_indicator",
            "mode": "internal_auto",
            "args": {"action_id": action_id},
            "result": {"reverted": True},
            "evidence_ids": [],
        }
    )
    ctx.metrics.block_reverted()
    return {"reverted": blk["value_defanged"]}


async def _upsert(ctx: ToolContext, a: UpsertArgs) -> dict[str, Any]:
    _inc(ctx, a.incident_id)

    def patch(inc: dict[str, Any]) -> None:
        inc.update(a.patch)

    ctx.incidents.update(a.incident_id, patch)
    return {"patched": sorted(a.patch)}


async def _raise_alert(ctx: ToolContext, a: RaiseAlertArgs) -> dict[str, Any]:
    inc = _inc(ctx, a.incident_id)
    if not ctx.alertmanager_url or ctx.http is None:
        raise ToolError("not_configured", "ALERTMANAGER_URL not set")
    summary = (inc.get("summary") or {}).get("en") or f"{inc['type']} incident"
    body = [
        {
            "labels": {
                "alertname": "FalconSentinelIncident",
                "severity": a.severity,
                "incident_id": a.incident_id,
                "type": inc["type"],
                "source": inc["source"],
            },
            "annotations": {"summary": summary[:300]},
            "startsAt": inc["created_at"],
        }
    ]
    resp = await ctx.http.post(f"{ctx.alertmanager_url.rstrip('/')}/api/v2/alerts", json=body)
    resp.raise_for_status()
    return {"posted": True}


async def _board(ctx: ToolContext, a: IncidentOnlyArgs) -> dict[str, Any]:
    inc = _inc(ctx, a.incident_id)
    card = {
        "incident_id": inc["incident_id"],
        "type": inc["type"],
        "severity": inc["severity"],
        "status": inc["status"],
        "brand_id": inc.get("brand_id"),
        "source": inc["source"],
        "indicator_count": len(inc["indicators"]),
        "updated_at": inc["updated_at"],
        "summary": inc.get("summary"),
    }
    await ctx.redis.xadd(BOARD_STREAM, {"data": json.dumps(card)}, maxlen=1000, approximate=True)
    return {"published": inc["incident_id"]}


async def _stix(ctx: ToolContext, a: IncidentOnlyArgs) -> dict[str, Any]:
    bundle = build_bundle(_inc(ctx, a.incident_id))
    return {"bundle": bundle, "objects": len(bundle["objects"])}


# ---------------------------------------------------------------- drafts (never sent)


def make_draft(inc: dict[str, Any], tool: str, recipient_kind: str) -> dict[str, Any]:
    doms = [i["value_defanged"] for i in inc["indicators"] if i["kind"] == "domain"]
    keys = inc.get("correlation_keys", {})
    reg = ", ".join(keys.get("registrar", [])) or "n/a"
    n = len(doms)
    lst = "\n".join(f"- {d}" for d in doms[:20])
    if tool == "draft_takedown":
        subject_en = f"Abuse report: {n} suspected phishing domains ({inc['incident_id']})"
        body_en = (
            f"Falcon Lens Sentinel observed {n} domains that appear to imitate a brand "
            f"({inc.get('brand_id') or 'unknown'}). Registrar signal: {reg}.\nDomains (defanged):\n{lst}\n"
            f"Evidence is available on request. This is a DRAFT awaiting operator approval."
        )
        body_ar = (
            f"رصد نظام عدسة الصقر {n} نطاقاً يبدو أنها تنتحل علامة تجارية ({inc.get('brand_id') or 'غير معروفة'}). "
            f"المسجّل: {reg}.\nالنطاقات (مُعطّلة الروابط):\n{lst}\nالأدلة متاحة عند الطلب. هذه مسودة بانتظار موافقة المشغّل."
        )
        kind = recipient_kind
    else:
        subject_en = f"Incident summary for review ({inc['incident_id']})"
        body_en = (
            f"Type: {inc['type']}, severity: {inc['severity']}, source: {inc['source']}.\n"
            f"Indicators (defanged):\n{lst}\nDRAFT for operator review; not sent by the Sentinel."
        )
        body_ar = (
            f"النوع: {inc['type']}، الخطورة: {inc['severity']}، المصدر: {inc['source']}.\n"
            f"المؤشرات (مُعطّلة الروابط):\n{lst}\nمسودة لمراجعة المشغّل؛ لا يرسلها النظام."
        )
        kind = "police"
    return {"recipient_kind": kind, "subject": subject_en, "body_ar": body_ar, "body_en": body_en}


# ---------------------------------------------------------------- dispatcher


async def run_read(ctx: ToolContext, tool: str, args: dict[str, Any]) -> ToolResult:
    if TOOL_MODE.get(tool) != "read":
        raise ToolError("bad_mode", tool)
    p = validate_args(tool, args)
    if isinstance(p, SearchVerdictsArgs):
        return ToolResult(True, "read", await _search_verdicts(ctx, p))
    if isinstance(p, FindRelatedArgs):
        return ToolResult(True, "read", await _find_related(ctx, p))
    if isinstance(p, PastIncidentsArgs):
        return ToolResult(True, "read", await _past_incidents(ctx, p))
    if not isinstance(p, NoArgs):  # pragma: no cover
        raise ToolError("bad_args", tool)
    return ToolResult(True, "read", await _feed_status(ctx, p))


async def run_action(
    ctx: ToolContext,
    tool: str,
    args: dict[str, Any],
    *,
    incident_id: str,
    action_id: str,
    evidence_ids: list[str],
    actor: str = "sentinel",
) -> ToolResult:
    """Execute one internal_auto action, or build the draft for an external_draft one. Always audited."""
    mode = TOOL_MODE.get(tool)
    if mode not in ("internal_auto", "external_draft"):
        raise ToolError("bad_mode", tool)
    p = validate_args(tool, args)
    result: dict[str, Any] = {}
    status = "executed"
    error: str | None = None
    try:
        if isinstance(p, RequeueArgs):
            result = await _requeue(ctx, incident_id, p)
        elif isinstance(p, BlockArgs):
            result = await _block(ctx, incident_id, action_id, p)
        elif isinstance(p, UpsertArgs):
            result = await _upsert(ctx, p)
        elif isinstance(p, RaiseAlertArgs):
            result = await _raise_alert(ctx, p)
        elif isinstance(p, TakedownArgs):
            result = {"draft": make_draft(_inc(ctx, p.incident_id), tool, p.recipient_kind)}
            status = "awaiting_approval"
        elif tool == "draft_police_report":
            result = {"draft": make_draft(_inc(ctx, incident_id), tool, "police")}
            status = "awaiting_approval"
        elif tool == "update_campaign_board":
            result = await _board(ctx, IncidentOnlyArgs(incident_id=incident_id))
        elif tool == "export_stix":
            result = await _stix(ctx, IncidentOnlyArgs(incident_id=incident_id))
            result = {"objects": result["objects"], "bundle_id": result["bundle"]["id"]}
        else:  # pragma: no cover
            raise ToolError("unknown_tool", tool)
    except ToolError as exc:
        if exc.reason in ("provenance", "bad_args", "not_found"):
            raise
        status, error = "failed", str(exc)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        status, error = "failed", f"{type(exc).__name__}: {exc}"
    ctx.metrics.action(tool, mode)
    await ctx.repo.audit_append(
        {
            "at": ctx.now(),
            "actor": actor,
            "incident_id": incident_id,
            "action_id": action_id,
            "tool": tool,
            "mode": mode,
            "args": args,
            "result": {
                "status": status,
                "error": error,
                **{k: v for k, v in result.items() if k != "draft"},
            },
            "evidence_ids": evidence_ids,
        }
    )
    return ToolResult(status != "failed", status, result, error)
