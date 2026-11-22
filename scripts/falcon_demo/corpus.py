"""The seed corpus. Defensive-only: no live phishing URL ever leaves this module.

Sources (each optional, a missing one is reported, never fatal):
  legit    evals/datasets/legit_urls.csv        defanged official URLs, sampled deterministically
  fixture  Falcon Demo Bank (.test domains)      built in, always present
  (red-team cases are never seeded: `make redteam` runs them)
  message  evals/datasets/{synthetic,human}_messages*.jsonl   {"text"}; kept if all domains reserved
  phish    evals/manifests/phishing.manifest.jsonl   hashes only -> verdict.created replay events
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .common import REPO_ROOT, SOURCE, refang

SENTINEL_DIR = REPO_ROOT / "services" / "sentinel"
if str(SENTINEL_DIR) not in sys.path:  # sentinel_core is a workspace package; this keeps plain `python` working
    sys.path.append(str(SENTINEL_DIR))

from sentinel_core.ids import make_ulid  # noqa: E402

GROUPS = ("fixture", "legit", "message", "phish")
# Red-team cases are NOT seeded: they run through `make redteam`, never the public API (reviewer B2).
SAFE_SUFFIXES = (".test", ".example", ".invalid")
_URL_RE = re.compile(r"(?i)\b(?:hxxps?|https?)(?:://|\[:\]//)[^\s<>\"')\]]+")
_DOMAIN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.|\[\.\]))+[a-z]{2,})(?![A-Za-z0-9-])"
)


def _host_ok(host: str) -> bool:
    h = host.lower().rstrip(".")
    return any(h == sfx[1:] or h.endswith(sfx) for sfx in SAFE_SUFFIXES)


def text_domains(text: str) -> set[str]:
    """Every host-like token in free text: scheme URLs, bare domains, defanged forms, e-mail domains."""
    found: set[str] = set()
    for m in _URL_RE.finditer(text):
        try:
            found.add((urlsplit(refang(m.group(0))).hostname or "").lower())
        except ValueError:
            found.add("unparseable-url.invalid!")  # fail closed: never matches the allowlist
    for m in _DOMAIN_RE.finditer(text):
        found.add(m.group(1).replace("[.]", ".").lower())
    found.discard("")
    return found


def message_allowed(text: str) -> bool:
    return all(_host_ok(h) for h in text_domains(text))


def item_allowed(item: Item) -> bool:
    """Final gate before the API: fixture URLs reserved-TLD only; legit URLs come from the curated CSV."""
    if item.kind == "message":
        return message_allowed(item.value)
    if item.kind == "url":
        if item.group == "legit":
            return True
        try:
            host = (urlsplit(refang(item.value)).hostname or "").lower()
        except ValueError:
            return False  # fail closed on unparseable input
        return item.group == "fixture" and _host_ok(host)
    return item.kind == "event" and item.group == "phish"


BRAND = "falcon_demo_bank"


@dataclass(frozen=True)
class Item:
    group: str
    kind: str  # url | message | event
    value: str  # url or message text; for `event` a sha256 (never a URL)
    expect: str | None = None  # dangerous | suspicious | no_warning_signs | None (unknown)
    extra: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> str:
        """Stable id used for idempotency and the seed state file."""
        return hashlib.sha256(f"{self.group}|{self.kind}|{self.value}".encode()).hexdigest()[:24]


# --- Falcon Demo Bank fixtures: fictional brand, reserved .test TLD -------------------------------------------
FIXTURE_URLS: tuple[tuple[str, str], ...] = (
    ("https://falcon-demo-bank.test/", "no_warning_signs"),
    ("https://falcon-demo-bank.test/ar/", "no_warning_signs"),
    ("https://falcon-demo-bank.test/login", "no_warning_signs"),
    ("https://falcon-demo-bank-secure-pay.test/", "dangerous"),  # combosquat
    ("https://falcon-demo-bnak.test/login", "dangerous"),  # typosquat
    ("https://falcon-dem0-bank.test/verify", "dangerous"),  # lookalike
    ("https://falcon-demo-bank-support.test/help", "suspicious"),
    ("https://falcondemobank-offers.test/", "suspicious"),
)
FIXTURE_MESSAGES: tuple[tuple[str, str], ...] = (
    (
        "بنك الصقر التجريبي: تم تعليق حسابك. أكمل التحقق خلال ساعة عبر falcon-demo-bank-secure-pay.test/verify",
        "dangerous",
    ),
    ("Falcon Demo Bank: your statement is ready in the app. We never ask for your PIN or OTP.", "no_warning_signs"),
    ("Falcon Demo Bank: pay AED 5 customs fee now to release your parcel: falcon-dem0-bank.test/pay", "dangerous"),
)


def fixture_items() -> list[Item]:
    items = [Item("fixture", "url", u, e) for u, e in FIXTURE_URLS]
    items += [Item("fixture", "message", t, e) for t, e in FIXTURE_MESSAGES]
    return items


def _every_kth(rows: list[Any], limit: int | None) -> list[Any]:
    if limit is None or limit >= len(rows):
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]


def legit_items(path: Path | None = None, limit: int | None = 60) -> list[Item]:
    p = path or REPO_ROOT / "evals" / "datasets" / "legit_urls.csv"
    if not p.is_file():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("url")]
    return [Item("legit", "url", refang(r["url"]), "no_warning_signs") for r in _every_kth(rows, limit)]


def _jsonl(path: Path) -> Iterator[dict[str, Any]]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj


def message_items(root: Path | None = None, limit: int | None = 60) -> list[Item]:
    d = root or REPO_ROOT / "evals" / "datasets"
    rows: list[dict[str, Any]] = []
    for pat in ("synthetic_messages*.jsonl", "human_messages*.jsonl"):
        for f in sorted(d.glob(pat)) if d.is_dir() else []:
            rows += [r for r in _jsonl(f) if r.get("text")]
    chosen = _every_kth(rows, limit)
    return [
        Item("message", "message", str(r["text"]), "dangerous" if r.get("label") == "scam" else None) for r in chosen
    ]


def phish_event_items(path: Path | None = None, limit: int | None = 50) -> list[Item]:
    """Hashes only. The manifest carries HMAC hashes, never the URL, so nothing live can leak."""
    p = path or REPO_ROOT / "evals" / "manifests" / "phishing.manifest.jsonl"
    if not p.is_file():
        return []
    rows = [r for r in _jsonl(p) if r.get("url_sha256")]
    return [
        Item(
            "phish",
            "event",
            str(r["url_sha256"]),
            "dangerous",
            (
                ("domain_sha256", str(r.get("registrable_domain_sha256", ""))),
                ("first_seen", str(r.get("first_seen", ""))),
            ),
        )
        for r in _every_kth(rows, limit)
    ]


def hash_event(item: Item) -> dict[str, Any]:
    """Deterministic verdict.created event for a hash-only phishing entry (same item -> same event_id)."""
    extra = dict(item.extra)
    try:
        at = datetime.fromisoformat(extra.get("first_seen", "").replace("Z", "+00:00"))
    except ValueError:
        at = datetime(2026, 11, 22, tzinfo=UTC)
    dom = extra.get("domain_sha256") or item.value
    return {
        "schema_version": "1.0",
        "event_id": f"evt_{make_ulid(at, 'seed|evt|' + item.value)}",
        "type": "verdict.created",
        "occurred_at": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "source": SOURCE,
        "verdict_id": f"vd_{make_ulid(at, 'seed|vd|' + item.value)}",
        "payload": {
            "verdict": "dangerous",
            "risk_score": 90,
            "input_type": "url",
            "registrable_domain": f"sha256-{dom[:16]}",
            "brand_id": None,
            "fingerprints": {},
            "top_signals": [],
        },
    }


def build_corpus(
    groups: tuple[str, ...] = GROUPS, legit_limit: int | None = 60, phish_limit: int | None = 50
) -> tuple[list[Item], dict[str, int], dict[str, int]]:
    """Returns (items, per-group counts kept, per-group counts skipped by the allowlist). Never prints contents."""
    parts: dict[str, list[Item]] = {
        "fixture": fixture_items(),
        "legit": legit_items(limit=legit_limit),
        "message": message_items(limit=None),
        "phish": phish_event_items(limit=phish_limit),
    }
    kept: dict[str, int] = {}
    skipped: dict[str, int] = {}
    items: list[Item] = []
    for g in GROUPS:
        if g not in groups:
            continue
        ok = [i for i in parts[g] if item_allowed(i)]
        if g == "message":
            ok = _every_kth(ok, 60)
        items += ok
        kept[g], skipped[g] = len(ok), sum(not item_allowed(i) for i in parts[g])
    return items, kept, skipped
