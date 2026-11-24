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

from falcon_core.provenance import effective_source

from .correlate import Features, correlation_keys, defang, extract
from .events import INCIDENT_SCHEMA_PATH, Event, parse_time
from .ids import make_ulid
from .rules import DEFAULT_RULES_PATH, SEVERITIES, Match, Rule, evaluate, load_rules

CHANNELS = frozenset({"web", "extension", "api", "mcp", "voice", "hunt"})
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
    def delete(self, incident_id: str) -> None: ...


class InMemoryIncidentStore:
    def __init__(self) -> None:
        self._by_id: dict[str, dict[str, Any]] = {}

    def get(self, incident_id: str) -> dict[str, Any] | None:
        inc = self._by_id.get(incident_id)
        return copy.deepcopy(inc) if inc else None

    def put(self, incident: dict[str, Any]) -> None:
        self._by_id[incident["incident_id"]] = copy.deepcopy(incident)

    def delete(self, incident_id: str) -> None:
        self._by_id.pop(incident_id, None)

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


def canonical_id(rule: Rule, group: str | None, earliest: datetime) -> str:
    """Arrival-order independent: rule id + correlation-group key + earliest occurred_at of the match."""
    return f"inc_{make_ulid(earliest, f'{rule.id}|{group}|{iso(earliest)}')}"


def is_pristine(inc: dict[str, Any]) -> bool:
    """Nothing external can reference the id yet: still open, no actions, no summary."""
    return inc.get("status") == "open" and not inc.get("actions") and not inc.get("summary")


# domain -> (first hunt verdict time, first user verdict-or-report time), over every event the Sentinel holds.
Firsts = dict[str, tuple[datetime | None, datetime | None]]


def detection_index(feats: Iterable[Features]) -> Firsts:
    """First hunt sighting and first person sighting per registrable domain (HUNTER.md section 4).

    Hunt = a verdict whose verdict_id is in the Sentinel's own hunt_candidates table (Features.origin).
    Person = any other verdict, or a report.submitted whose verdict_id points at a verdict of that domain."""
    feats = list(feats)
    dom_of_vid = {f.event.verdict_id: f.domain for f in feats if f.event.verdict_id and f.domain}
    hunt: dict[str, datetime] = {}
    user: dict[str, datetime] = {}
    for f in feats:
        at = f.event.occurred_at
        if f.event.type in ("verdict.created", "verdict.upgraded") and f.domain:
            target = hunt if f.origin == "hunt" else user
            if f.domain not in target or at < target[f.domain]:
                target[f.domain] = at
        elif f.event.type == "report.submitted":
            vid = f.event.verdict_id or f.event.payload.get("verdict_id")
            dom = dom_of_vid.get(vid) if isinstance(vid, str) else None
            if dom and (dom not in user or at < user[dom]):
                user[dom] = at
    return {d: (hunt.get(d), user.get(d)) for d in sorted({*hunt, *user})}


def detection_block(domains: Iterable[str], firsts: Firsts, existing: dict[str, Any] | None) -> dict[str, Any] | None:
    """contracts/incident.schema.json `detection`; None when the hunt saw none of the domains.
    found_before_report: every domain's first sighting is a hunt verdict with no older person sighting.
    Once false it stays false (it never flips back)."""
    doms = sorted(set(domains))
    pairs = [firsts.get(d, (None, None)) for d in doms]
    hunts = [h for h, _u in pairs if h is not None]
    users = [u for _h, u in pairs if u is not None]
    if not hunts:
        return None
    before = bool(doms) and all(h is not None and (u is None or h < u) for h, u in pairs)
    old = (existing or {}).get("detection") or {}
    if old.get("found_before_report") is False:
        before = False
    origin = "hunt" if not users else ("mixed" if hunts else "user")
    return {
        "origin": origin,
        "found_before_report": before,
        "first_hunt_seen": iso(min(hunts)),
        "first_user_seen": iso(min(users)) if users else None,
    }


def build_incident(
    rule: Rule,
    feats: Sequence[Features],
    triggered_at: datetime,
    existing: dict[str, Any] | None = None,
    group: str | None = None,
    absorbed: Sequence[dict[str, Any]] = (),
    firsts: Firsts | None = None,
) -> dict[str, Any]:
    """Deterministic parts only. `existing` keeps agent-enriched fields (status, summary, actions...).

    Id policy (L1 decision): canonical id = f(rule, group key, earliest occurred_at). A published id stays
    stable, except that a pristine incident of the same type is re-keyed to the canonical id (old id kept as
    an alias in the timeline). Absorbed incidents (group merges) are deleted by the caller; their ids become aliases."""
    fs = sorted(feats, key=lambda f: (f.event.occurred_at, f.event.event_id))
    earliest = fs[0].event.occurred_at
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
    domains = sorted({f.domain for f in fs if f.domain})
    detection = detection_block(domains, firsts or {}, existing)
    indicators = []
    for (kind, value), seen in sorted(first_seen.items()):
        ind = {
            "kind": kind,
            "value_defanged": value,
            "sha256": _sha(value.replace("[.]", ".")),
            "first_seen": iso(seen),
            "blocked_until": None,
        }
        if (kind, value) in old_ind:
            ind["blocked_until"] = old_ind[(kind, value)].get("blocked_until")
        if detection is not None and kind == "domain":
            h, u = (firsts or {}).get(value.replace("[.]", "."), (None, None))
            if h is not None or u is not None:
                ind["found_by"] = "hunt" if h is not None and (u is None or h < u) else "user"
        indicators.append(ind)

    same_type = existing is None or existing["type"] == rule.type
    canon = canonical_id(rule, group, earliest)
    iid = canon if existing is None else existing["incident_id"]
    aliases = [a["incident_id"] for a in absorbed]
    if existing is not None and same_type and is_pristine(existing) and existing["incident_id"] != canon:
        aliases.append(existing["incident_id"])
        iid = canon

    created_cands = [parse_time(existing["created_at"])] if existing else []
    if same_type:
        created_cands.append(triggered_at)
    created = min(created_cands)

    carried = [t for src in [existing, *absorbed] if src for t in src["timeline"] if "event_id" not in t]
    carried = [t for t in carried if not t["what"].startswith(f"rule {rule.id} fired")]
    extra = [{"at": iso(created), "what": f"alias {a}"} for a in aliases]
    extra.append({"at": iso(triggered_at), "what": f"rule {rule.id} fired ({rule.type})"})
    events_tl = [
        {
            "at": iso(f.event.occurred_at),
            "what": f"{f.event.type} {defang(f.domain) if f.domain else ''}".strip(),
            "event_id": f.event.event_id,
        }
        for f in fs
    ]
    seen_tl: set[tuple[str, str]] = set()
    timeline = []
    for t in sorted(
        events_tl + carried + extra,
        key=lambda t: (parse_time(t["at"]), t.get("event_id", ""), t["what"]),
    ):
        k = (t["at"], t["what"])
        if k not in seen_tl:
            seen_tl.add(k)
            timeline.append(t)

    brands = sorted({f.brand_id for f in fs if f.brand_id})
    sources = {f.event.source for f in fs}
    source = next(s for s in SOURCE_PRIORITY if s in sources)
    # Label at source: checks of internal fixture hosts (config allow-list) are fixtures, not live.
    source = effective_source(source, (f.domain for f in fs if f.domain))
    keys = correlation_keys(fs)
    if group:
        keys["group"] = group
    others = [existing, *absorbed] if existing else list(absorbed)
    rule_ids = sorted({rule.id, *(r for o in others for r in o["rule_ids"])})
    severity = rule.severity_floor
    for o in others:
        severity = _max_sev(severity, o["severity"])
    updated = max([f.event.occurred_at for f in fs] + ([parse_time(existing["updated_at"])] if existing else []))

    channel_set = {ch for f in fs if isinstance((ch := f.event.payload.get("channel")), str) and ch in CHANNELS}
    channel_set |= {c for o in others for c in o.get("channels", ())}
    inc: dict[str, Any] = dict(existing or {})
    if channel_set:  # contracts/incident.schema.json `channels`: which clients the linked checks came from
        inc["channels"] = sorted(channel_set)
    if detection is not None:  # contracts/incident.schema.json `detection` (hunt mode)
        inc["detection"] = detection
    inc.update(
        {
            "incident_id": iid,
            "type": existing["type"] if existing else rule.type,
            "severity": severity,
            "status": existing.get("status", "open") if existing else "open",
            "brand_id": brands[0] if len(brands) == 1 else None,
            "rule_ids": rule_ids,
            "correlation_keys": keys,
            "indicators": indicators,
            "linked_verdicts": sorted({f.event.verdict_id for f in fs if f.event.verdict_id}),
            "timeline": timeline,
            "actions": existing.get("actions", []) if existing else [],
            "source": source,
            "created_at": iso(created),
            "updated_at": iso(updated),
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
        self._firsts: Firsts = {}

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
        self._firsts = detection_index(all_feats)
        changed: list[str] = []
        for rule in self.rules:
            for m in evaluate(rule, all_feats, self.vectors):
                iid = self._upsert(m)
                if iid and iid not in changed:
                    changed.append(iid)
        live = {i["incident_id"] for i in self.store.all()}
        return [i for i in changed if i in live]

    def _classify(self, m: Match) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """(survivor, absorbed). Survivor = oldest incident of this rule's type or a fold target."""
        absorbable_rules = {r.id for r in self.rules if m.rule.id in r.merge_into}
        cands: dict[str, dict[str, Any]] = {}
        for f in m.features:
            for inc in self.store.find_by_event(f.event.event_id):
                cands[inc["incident_id"]] = inc
        keep: list[dict[str, Any]] = []
        absorb: list[dict[str, Any]] = []
        for inc in sorted(cands.values(), key=lambda i: (parse_time(i["created_at"]), i["incident_id"])):
            ids = set(inc["rule_ids"])
            same = inc["type"] == m.rule.type and m.rule.id in ids
            fold = bool(set(m.rule.merge_into) & ids)
            if same or fold:
                keep.append(inc)
            elif ids <= absorbable_rules:
                absorb.append(inc)
        if not keep:
            return None, absorb
        survivor = keep[0]
        absorb += [k for k in keep[1:] if k["type"] == m.rule.type]  # group merge: older id survives
        return survivor, absorb

    def _upsert(self, m: Match) -> str | None:
        survivor, absorbed = self._classify(m)
        feats: dict[str, Features] = {f.event.event_id: f for f in m.features}
        for src in [survivor, *absorbed]:
            for t in (src or {}).get("timeline", []):
                eid = t.get("event_id")
                if eid and eid in self._feats:
                    feats.setdefault(eid, self._feats[eid])
        inc = build_incident(m.rule, list(feats.values()), m.triggered_at, survivor, m.group, absorbed, self._firsts)
        if survivor == inc and not absorbed:
            return None
        for a in absorbed:
            self.store.delete(a["incident_id"])
        if survivor and survivor["incident_id"] != inc["incident_id"]:
            self.store.delete(survivor["incident_id"])
        self.store.put(inc)
        return str(inc["incident_id"])
