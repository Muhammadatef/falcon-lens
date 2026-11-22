"""Template reasons and actions (SCORING §5) plus the adapter to the verdict contract shape.

Reasons: at most three, hard-rule reasons first (they decide the verdict), then by |weight|.
Every reason cites evidence ids taken from ``result.weighted_evidence``, so it always cites
existing ids. The LLM responder may replace these, but the verifier falls back to them.

TODO(T-002): return the pydantic ``Reason`` / ``Actions`` models from ``falcon_core.contracts``.
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

import yaml

from falcon_core.i18n import LANGS, Catalog, Lang, load_catalog
from falcon_core.scoring.arbiter import ArbiterResult, Verdict
from falcon_core.scoring.evidence import Evidence, to_contract

MAX_REASONS = 3
REPORTING_CHANNELS_ENV = "FL_REPORTING_CHANNELS"


@dataclass(frozen=True, slots=True)
class ReasonSlot:
    """Language-neutral reason: a catalog key plus the evidence ids it cites."""

    section: str  # "hard_rules" | "reasons" | "degraded"
    key: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplateReason:
    text: str
    evidence_ids: tuple[str, ...]
    key: str


def template_key(ev: Evidence) -> str:
    if ev.signal.startswith("rep."):
        return "rep.feed_hit"
    if ev.signal == "domain.age":
        return "domain.age.new" if ev.weight > 0 else "domain.age.old"
    return ev.signal


def _has_text(slot: ReasonSlot) -> bool:
    for lang in LANGS:
        cat = load_catalog(lang)
        if slot.section == "degraded":
            continue
        table = cat.hard_rules if slot.section == "hard_rules" else cat.reasons
        if slot.key not in table:
            return False
    return True


def select_reasons(result: ArbiterResult) -> list[ReasonSlot]:
    """Choose up to three reasons. Same choice for every language."""
    by_id = {e.id: e for e in result.weighted_evidence}
    risk_verdict = result.verdict != "no_warning_signs"
    ranked: list[tuple[int, float, int, ReasonSlot]] = []
    order = 0

    def push(priority: int, magnitude: float, slot: ReasonSlot) -> None:
        nonlocal order
        if slot.evidence_ids and _has_text(slot):
            ranked.append((priority, -magnitude, order, slot))
            order += 1

    errored = tuple(i for i in result.errored_evidence_ids if i in by_id)
    if result.degraded_override:
        push(0, 0.0, ReasonSlot("degraded", "degraded", errored))

    consumed: set[str] = set()
    for rule in result.fired_rules:
        ids = tuple(i for i in rule.evidence_ids if i in by_id)
        mag = sum(abs(by_id[i].weight) for i in ids)
        push(1, mag, ReasonSlot("hard_rules", rule.rule_id, ids))
        consumed.update(ids)

    groups: dict[str, list[Evidence]] = {}
    for ev in result.weighted_evidence:
        if ev.id in consumed or ev.weight == 0 or ev.error is not None:
            continue
        if risk_verdict and ev.weight < 0:
            continue  # do not soften a warning with trust reasons
        if not risk_verdict and ev.weight > 0:
            continue  # below the threshold: explain with trust evidence only
        groups.setdefault(template_key(ev), []).append(ev)
    for key, evs in groups.items():
        push(2, max(abs(e.weight) for e in evs), ReasonSlot("reasons", key, tuple(e.id for e in evs)))

    if result.degraded and not result.degraded_override:
        push(3, 0.0, ReasonSlot("degraded", "degraded", errored))

    ranked.sort(key=lambda t: (t[0], t[1], t[2]))
    return [slot for *_, slot in ranked[:MAX_REASONS]]


def _render(slot: ReasonSlot, cat: Catalog) -> str:
    if slot.section == "degraded":
        return cat.degraded
    if slot.section == "hard_rules":
        return cat.hard_rules[slot.key]
    return cat.reasons[slot.key]


def template_reasons(result: ArbiterResult, lang: Lang) -> list[TemplateReason]:
    cat = load_catalog(lang)
    return [TemplateReason(_render(s, cat), s.evidence_ids, f"{s.section}.{s.key}") for s in select_reasons(result)]


def contract_reasons(result: ArbiterResult) -> list[dict[str, object]]:
    """Reasons in the verdict.schema.json shape (both languages, ``generated_by=template``)."""
    ar, en = load_catalog("ar"), load_catalog("en")
    return [
        {
            "ar": _render(s, ar),
            "en": _render(s, en),
            "evidence_ids": list(s.evidence_ids),
            "generated_by": "template",
        }
        for s in select_reasons(result)
    ]


# --- reporting channels -------------------------------------------------------------------------


def _default_channels_path() -> Path | None:
    env = os.environ.get(REPORTING_CHANNELS_ENV)
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "reporting_channels.yaml"
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True, slots=True)
class ReportingChannels:
    channels: tuple[dict[str, str], ...]  # contract shape, verified entries only
    generic_ar: str | None
    generic_en: str | None


def parse_reporting_channels(raw: object) -> ReportingChannels:
    """Keep only entries that carry an https source_url and a retrieved_at date (CLAUDE.md rule)."""
    if not isinstance(raw, dict):
        return ReportingChannels((), None, None)
    data = cast(dict[str, object], raw)
    source_url = data.get("source_url")
    retrieved = data.get("retrieved_at")
    if isinstance(retrieved, dt.date):
        retrieved = retrieved.isoformat()
    generic = data.get("generic_fallback")
    g = cast(dict[str, object], generic) if isinstance(generic, dict) else {}
    g_ar, g_en = g.get("ar"), g.get("en")
    generic_ar = g_ar if isinstance(g_ar, str) else None
    generic_en = g_en if isinstance(g_en, str) else None
    verified = (
        isinstance(source_url, str)
        and source_url.startswith("https://")
        and isinstance(retrieved, str)
        and _is_iso_date(retrieved)
    )
    channels: list[dict[str, str]] = []
    entries = data.get("channels")
    if verified and isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            e = cast(dict[str, object], entry)
            la, le, val = e.get("label_ar"), e.get("label_en"), e.get("value")
            if isinstance(la, str) and isinstance(le, str) and isinstance(val, str) and la and le and val:
                channels.append(
                    {
                        "label_ar": la,
                        "label_en": le,
                        "value": val,
                        "source_url": cast(str, source_url),
                        "retrieved_at": cast(str, retrieved),
                    }
                )
    return ReportingChannels(tuple(channels), generic_ar, generic_en)


def _is_iso_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


@lru_cache(maxsize=4)
def load_reporting_channels(path: str | None = None) -> ReportingChannels:
    p = Path(path) if path else _default_channels_path()
    if p is None or not p.is_file():
        return ReportingChannels((), None, None)
    with open(p, encoding="utf-8") as fh:
        return parse_reporting_channels(yaml.safe_load(fh))


def report_block(channels: ReportingChannels) -> dict[str, object]:
    ar, en = load_catalog("ar"), load_catalog("en")
    if channels.channels:
        return {
            "ar": ar.report["with_channels"],
            "en": en.report["with_channels"],
            "channels": [dict(c) for c in channels.channels],
        }
    return {
        "ar": channels.generic_ar or ar.report["generic"],
        "en": channels.generic_en or en.report["generic"],
        "channels": [],
    }


def template_actions(verdict: Verdict, channels: ReportingChannels | None = None) -> dict[str, object]:
    """Actions in verdict.schema.json shape. ``caution`` is always set for no_warning_signs."""
    ch = channels if channels is not None else load_reporting_channels()
    ar, en = load_catalog("ar"), load_catalog("en")
    out: dict[str, object] = {
        "now": {"ar": list(ar.actions[verdict]["now"]), "en": list(en.actions[verdict]["now"])},
        "if_already_acted": {
            "ar": list(ar.actions[verdict]["if_already_acted"]),
            "en": list(en.actions[verdict]["if_already_acted"]),
        },
        "report": report_block(ch),
    }
    if verdict == "no_warning_signs":
        out["caution"] = {"ar": list(ar.caution), "en": list(en.caution)}
    return out


def verdict_core_fields(result: ArbiterResult, channels: ReportingChannels | None = None) -> dict[str, object]:
    """Arbiter-owned part of a verdict.schema.json object. The cascade adds ids, timing, tier."""
    out: dict[str, object] = {
        "verdict": result.verdict,
        "risk_score": result.risk_score,
        "calibrated_probability": round(result.calibrated_probability, 6),
        "evidence": [to_contract(e) for e in result.weighted_evidence],
        "reasons": contract_reasons(result),
        "actions": template_actions(result.verdict, channels),
        "degraded": result.degraded,
    }
    if result.degraded_reasons:
        out["degraded_reasons"] = list(result.degraded_reasons)
    return out


def all_template_keys(signals: Sequence[str]) -> list[str]:
    """Catalog keys the given signal names can render to (used by coverage tests)."""
    keys: list[str] = []
    for s in signals:
        if s.startswith("rep."):
            keys.append("rep.feed_hit")
        elif s == "domain.age":
            keys += ["domain.age.new", "domain.age.old"]
        else:
            keys.append(s)
    return keys
