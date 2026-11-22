"""Rules engine: evaluates services/sentinel/rules.yaml over correlation features."""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from .correlate import Features, group_label, sessions, window_trigger

DEFAULT_RULES_PATH = Path(
    os.environ.get("FL_SENTINEL_RULES") or Path(__file__).resolve().parents[1] / "rules.yaml"
)
INCIDENT_TYPES = {"campaign", "kit_reuse", "report_burst", "reputation_flip", "quality"}
SEVERITIES = ("low", "medium", "high", "critical")


class RuleConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    id: str
    type: str
    detector: str
    event_types: tuple[str, ...]
    group_by: str
    window: timedelta
    severity_floor: str
    where: dict[str, Any]
    distinct: str = "event_id"
    min_count: int = 1
    merge_into: tuple[str, ...] = ()
    from_verdicts: tuple[str, ...] = ()
    to_verdicts: tuple[str, ...] = ()
    new_domains: bool = False


@dataclass(frozen=True)
class Match:
    rule: Rule
    group: str
    features: tuple[Features, ...]
    triggered_at: datetime


def load_rules(path: Path | str = DEFAULT_RULES_PATH) -> list[Rule]:
    data = yaml.safe_load(Path(path).read_text())
    rules: list[Rule] = []
    seen: set[str] = set()
    for r in data.get("rules", []):
        try:
            rule = Rule(
                id=r["id"],
                type=r["type"],
                detector=r["detector"],
                event_types=tuple(r["event_types"]),
                group_by=r["group_by"],
                window=timedelta(minutes=int(r["window_minutes"])),
                severity_floor=r["severity_floor"],
                where=r.get("where") or {},
                distinct=r.get("distinct", "event_id"),
                min_count=int(r.get("min_count", 1)),
                merge_into=tuple(r.get("merge_into", ())),
                from_verdicts=tuple(r.get("from_verdicts", ())),
                to_verdicts=tuple(r.get("to_verdicts", ())),
                new_domains=bool(r.get("new_domains", False)),
            )
        except KeyError as exc:
            raise RuleConfigError(f"rule {r.get('id')}: missing {exc}") from exc
        if rule.id in seen:
            raise RuleConfigError(f"duplicate rule id {rule.id}")
        if rule.type not in INCIDENT_TYPES:
            raise RuleConfigError(f"rule {rule.id}: unknown incident type {rule.type}")
        if rule.severity_floor not in SEVERITIES:
            raise RuleConfigError(f"rule {rule.id}: bad severity_floor")
        if rule.detector not in ("threshold", "flip"):
            raise RuleConfigError(f"rule {rule.id}: unknown detector {rule.detector}")
        seen.add(rule.id)
        rules.append(rule)
    return rules


def _cond_ok(value: Any, cond: Any) -> bool:
    if isinstance(cond, dict):
        if "in" in cond and value not in cond["in"]:
            return False
        if "not_in" in cond and value in cond["not_in"]:
            return False
        return not ("exists" in cond and (value not in (None, "", False)) != bool(cond["exists"]))
    return bool(value == cond)


def _selected(rule: Rule, feats: Sequence[Features]) -> list[Features]:
    return [
        f
        for f in feats
        if f.event.type in rule.event_types
        and all(_cond_ok(f.get(k), c) for k, c in rule.where.items())
    ]


def _unit(f: Features, name: str) -> str | None:
    """Distinct-counting unit; None = the event lacks the feature and must not count."""
    if name == "event_id":
        return f.event.event_id
    v = f.get(name)
    return str(v) if v not in (None, "") else None


def _flip_matches(rule: Rule, sel: Sequence[Features]) -> list[Match]:
    """R4: any `to` verdict preceded (within window) by a `from` verdict on the same domain, or carrying
    previous_verdict in `from`. One match per flip: later `to` events with the same from-event are skipped."""
    by_dom: dict[str, list[Features]] = defaultdict(list)
    for f in sel:
        if f.domain and f.verdict:
            by_dom[f.domain].append(f)
    out: list[Match] = []
    for dom, fs in by_dom.items():
        fs.sort(key=lambda x: (x.event.occurred_at, x.event.event_id))
        used: set[str] = set()
        for i, cur in enumerate(fs):
            if cur.verdict not in rule.to_verdicts:
                continue
            prevs = [
                p
                for p in fs[:i]
                if p.verdict in rule.from_verdicts
                and cur.event.occurred_at - p.event.occurred_at <= rule.window
            ]
            if prevs:
                if prevs[0].event.event_id in used:
                    continue
                used.add(prevs[0].event.event_id)
                out.append(Match(rule, f"domain:{dom}", (prevs[0], cur), cur.event.occurred_at))
            elif cur.prev_verdict in rule.from_verdicts and cur.event.event_id not in used:
                used.add(cur.event.event_id)
                out.append(Match(rule, f"domain:{dom}", (cur,), cur.event.occurred_at))
    return out


def evaluate(
    rule: Rule, feats: Sequence[Features], vectors: dict[str, list[float]] | None = None
) -> list[Match]:
    """Pure function: same features in, same matches out (sorted by trigger time then group)."""
    sel = _selected(rule, feats)
    matches: list[Match] = []
    if rule.detector == "flip":
        matches = _flip_matches(rule, sel)
    else:
        if rule.new_domains:
            # "new" = first observed (any event type) no earlier than one window before this event
            first: dict[str, datetime] = {}
            for f in feats:
                if f.domain and (f.domain not in first or f.event.occurred_at < first[f.domain]):
                    first[f.domain] = f.event.occurred_at
            sel = [
                f for f in sel if f.domain and f.event.occurred_at - first[f.domain] <= rule.window
            ]
        labels = group_label(sel, rule.group_by, vectors)
        groups: dict[str, list[Features]] = defaultdict(list)
        for f in sel:
            lab = labels[f.event.event_id]
            if lab is not None:
                groups[lab].append(f)
        for lab, fs in groups.items():
            for sess in sessions(fs, rule.window):
                times = [
                    (f.event.occurred_at, u)
                    for f in sess
                    if (u := _unit(f, rule.distinct)) is not None
                ]
                trig = window_trigger(times, rule.window, rule.min_count)
                if trig is not None:
                    matches.append(Match(rule, lab, tuple(sess), trig))
    matches.sort(key=lambda m: (m.triggered_at, m.group))
    return matches
