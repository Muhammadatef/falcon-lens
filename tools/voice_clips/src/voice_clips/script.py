"""Script loading and manifest building."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

LANGS = ("ar_ae", "en")


@dataclass(frozen=True)
class Clip:
    id: str
    lang: str
    text: str


def load_script(path: Path) -> list[Clip]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = data["clips"] if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: expected a non-empty `clips:` list")
    out: list[Clip] = []
    seen: set[str] = set()
    for item in raw:
        cid, lang, text = str(item["id"]), str(item["lang"]), str(item["text"]).strip()
        if lang not in LANGS:
            raise ValueError(f"clip {cid}: lang must be one of {LANGS}, got {lang!r}")
        if cid in seen:
            raise ValueError(f"duplicate clip id {cid}")
        if not text:
            raise ValueError(f"clip {cid}: empty text")
        seen.add(cid)
        out.append(Clip(cid, lang, text))
    return out


MANIFEST_KEYS = ("id", "file", "text", "ms", "engine", "voice")


def manifest_entry(clip: Clip, file: str, ms: int, engine: str, voice: str) -> dict[str, Any]:
    return {"id": clip.id, "file": file, "text": clip.text, "ms": ms, "engine": engine, "voice": voice}


def validate_manifest(manifest: list[dict[str, Any]], clips: list[Clip]) -> None:
    """Every script id has exactly one entry with the full key set; no extras."""
    ids = [m["id"] for m in manifest]
    want = {c.id for c in clips}
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids in manifest")
    if set(ids) != want:
        raise ValueError(
            f"manifest ids differ from script: missing={sorted(want - set(ids))} extra={sorted(set(ids) - want)}"
        )
    for m in manifest:
        if tuple(m) != MANIFEST_KEYS:
            raise ValueError(f"manifest entry {m.get('id')}: keys must be {MANIFEST_KEYS}")
        if not isinstance(m["ms"], int) or m["ms"] <= 0:
            raise ValueError(f"manifest entry {m['id']}: ms must be a positive int")


def write_manifest(out: Path, manifest: list[dict[str, Any]]) -> Path:
    p = out / "manifest.json"
    p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
