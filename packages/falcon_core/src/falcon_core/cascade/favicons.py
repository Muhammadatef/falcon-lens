"""Reference favicon hashes per brand (``favicon_hash`` in data/brands.yaml; sha256 hex)."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _brands_yaml() -> Path | None:
    env = os.environ.get("FALCON_BRANDS_YAML")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "data" / "brands.yaml"
        if cand.is_file():
            return cand
    return None


def load_brand_favicons(path: Path | None = None) -> dict[str, str]:
    """Map favicon sha256 -> brand_id. Entries without a valid sha256 are skipped."""
    p = path or _brands_yaml()
    if p is None or not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for entry in data.get("brands", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        h = str(entry.get("favicon_hash") or "").lower().removeprefix("sha256:")
        if _SHA256.match(h) and entry.get("brand_id"):
            out[h] = str(entry["brand_id"])
    return out
