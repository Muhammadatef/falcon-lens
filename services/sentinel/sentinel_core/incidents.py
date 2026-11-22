"""Incident building (schema-valid, deterministic ids) and the idempotent Sentinel driver."""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from .correlate import Features, correlation_keys, defang, extract
from .events import INCIDENT_SCHEMA_PATH, Event
from .ids import make_ulid
from .rules import DEFAULT_RULES_PATH, SEVERITIES, Match, Rule, evaluate, load_rules

SOURCE_PRIORITY = ("live", "replay", "synthetic", "fixture")


@lru_cache(maxsize=1)
def _incident_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(INCIDENT_SCHEMA_PATH.read_text()))


def validate_incident(incident: dict[str, Any]) -> None:
    errs = sorted(_incident_validator().iter_errors(incident), key=lambda e: list(e.path))
    if errs:
        raise ValueError("invalid incident: " + "; ".join(e.message for e in errs[:3]))


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class IncidentStore(Protocol):
    def get(self, incident_id: str) -> dict[str, Any] | None: ...
    def put(self, incident: dict[str, Any]) -> None: ...
    def all(self) -> list[dict[str, Any]]: ...
    def find_by_event(self, event_id: str) -> list[dict[str, Any]]: ...


class InMemoryIncidentStore:
    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}

    def get(self, incident_id: str) -> dict[str, Any] | None:
        inc = self._by_id.get(incident_id)
        return copy.deepcopy(inc) if inc else None

    def put(self, incident: dict[str, Any]) -> None:
        self._by_id[incident["incident_id"]] = copy.deepcopy(incident)

    def all(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self._by_id[k]) for k in sorted(self._by_id)]

    def find_by_event(self, event_id: str) -> list[dict[str, Any]]:
        return [
            copy.deepcopy(i)
            for k, i in sorted(self._by_id.items())
            if any(t.get("event_id") == event_id for t in i["timeline"])
        ]


def _max_sev(a: str, b: str) -> str:
    return a if SEVERITIES.index(a) >= SEVERITIES.index(b) else b


def build_incident(
    rule: Rule,
    feats: Sequence[Features],
    triggered_at: datetime,
    existing: dict[str, Any] | None = None,
    group: str | None = None,
) -> dict[str, Any]:
    """Deterministic parts only. `existing` keeps agent-enriched fields (status, summary, actions...)."""
    fs = sorted(feats, key=lambda f: (f.event.occurred_at, f.event.event_id))
    first = fs[0].event
    first_seen: dict[tuple[str, str], datetime] = {}
    for f in fs:
        cands: list[tuple[str, str]] = []
        if f.domain:
            cands.append(("domain", defang(f.domain)))
        if f.dom_simhash is not None:
            cands.append(("dom_hash", f"{f.dom_simhash:016x}"))
        if f.script_fp:
            cands.append(("script_cluster", f.script_fp))
        for c in cands:
            first_seen.setdefault(c, f.event.occurred_at)
    old_ind = {(i["kind"], i["value_defanged"]): i for i in (existing or {}).get("indicators", [])}
    indicators = []
    for (kind, value), seen in sorted(first_seen.items()):
        ind = {"kind": kind, "value_defanged": value, "sha256": _sha(value.replace("[.]", ".")), "first_seen": iso(seen), "blocked_until": None}
        if (kind, value) in old_ind:
            ind = {**ind, **{k: v for k, v in old_ind[(kind, value)].items() if k in ("blocked_until",)}}
        indicators.append(ind)

    timeline = [
        {"at": iso(f.event.occurred_at), "what": f"{f.event.type} {defang(f.domain) if f.domain else ''}".strip(), "event_id": f.event.event_id}
        for f in fs
    ]
    fired = {"at": iso(triggered_at), "what": f"rule {rule.id} fired ({rule.type})"}
    prior_fired = [t for t in (existing or {}).get("timeline", []) if "event_id" not in t]
    if fired not in prior_fired:
        prior_fired.append(fired)
    timeline = sorted(timeline + prior_fired, key=lambda t: (t["at"], t.get("event_id", "")))

    brands = sorted({f.brand_id for f in fs if f.brand_id})
    sources = {f.event.source for f in fs}
    source = next(s for s in SOURCE_PRIORITY if s in sources)
    keys = correlation_keys(fs)
    if group:
        keys["group"] = group
    rule_ids = sorted({rule.id, *(existing or {}).get("rule_ids", [])})
    severity = _max_sev(rule.severity_floor, (existing or {}).get("severity", "low"))
    created = (existing or {}).get("created_at") or iso(triggered_at)
    updated = max(iso(fs[-1].event.occurred_at), (existing or {}).get("updated_at", ""))

    inc: dict[str, Any] = dict(existing or {})
    inc.update(
        {
            "incident_id": (existing or {}).get("incident_id")
            or f"inc_{make_ulid(triggered_at, f'{rule.id}|{first.event_id}')}",
            "type": (existing or {}).get("type", rule.type),
            "severity": severity,
            "status": (existing or {}).get("status", "open"),
            "brand_id": brands[0] if len(brands) == 1 else None,
            "rule_ids": rule_ids,
            "correlation_keys": keys,
            "indicators": indicators,
            "linked_verdicts": sorted({f.event.verdict_id for f in fs if f.event.verdict_id}),
            "timeline": timeline,
            "actions": (existing or {}).get("actions", []),
            "source": source,
            "created_at": created,
            "updated_at": updated,
        }
    )
    validate_incident(inc)
    return inc


class Sentinel:
    """Idempotent driver: feed events (any order, any number of replays) and incidents converge."""

    def __init__(
        self,
        store: IncidentStore,
        vectors: dict[str, list[float]] | None = None,
        rules_path: Path | str | None = None,
        official_domains: Iterable[str] = (),
    ) -> None:
        self.store = store
        self.vectors = vectors or {}
        self.rules = load_rules(rules_path or DEFAULT_RULES_PATH)
        self.official = frozenset(official_domains)
        self._feats: dict[str, Features] = {}

    def process(self, events: Iterable[Event]) -> list[str]:
        """Returns ids of incidents created or changed by this batch."""
        added = False
        for ev in events:
            if ev.event_id not in self._feats:  # idempotent on event_id
                self._feats[ev.event_id] = extract(ev, self.official)
                added = True
        if not added:
            return []
        all_feats = sorted(self._feats.values(), key=lambda f: (f.event.occurred_at, f.event.event_id))
        changed: list[str] = []
        for rule in self.rules:
            for m in evaluate(rule, all_feats, self.vectors):
                iid = self._upsert(m)
                if iid and iid not in changed:
                    changed.append(iid)
        return changed

    def _find_target(self, m: Match) -> dict[str, Any] | None:
        cands: dict[str, dict[str, Any]] = {}
        for f in m.features:
            for inc in self.store.find_by_event(f.event.event_id):
                same = inc["type"] == m.rule.type and m.rule.id in inc["rule_ids"]
                fold = bool(set(m.rule.merge_into) & set(inc["rule_ids"]))
                if same or fold:
                    cands[inc["incident_id"]] = inc
        if not cands:
            return None
        return sorted(cands.values(), key=lambda i: (i["created_at"], i["incident_id"]))[0]

    def _upsert(self, m: Match) -> str | None:
        existing = self._find_target(m)
        feats: dict[str, Features] = {f.event.event_id: f for f in m.features}
        if existing:
            for t in existing["timeline"]:
                eid = t.get("event_id")
                if eid and eid in self._feats:
                    feats.setdefault(eid, self._feats[eid])
        inc = build_incident(m.rule, list(feats.values()), m.triggered_at, existing, m.group)
        if existing == inc:
            return None
        self.store.put(inc)
        return str(inc["incident_id"])
