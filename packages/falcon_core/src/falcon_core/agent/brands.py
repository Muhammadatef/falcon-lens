"""Brand ids and verified domains from ``data/brands.yaml`` (path override: ``FL_BRANDS_PATH``).

A minimal reader for the agents (only ids and verified domains). The signals package owns the
full brand registry; this module avoids depending on it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

BRANDS_ENV = "FL_BRANDS_PATH"


@dataclass(frozen=True, slots=True)
class BrandIndex:
    verified_domains: Mapping[str, frozenset[str]]

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self.verified_domains)


def _find_brands_yaml() -> Path | None:
    env = os.environ.get(BRANDS_ENV)
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        cand = parent / "data" / "brands.yaml"
        if cand.is_file():
            return cand
    return None


def parse_brands(raw: object) -> BrandIndex:
    out: dict[str, frozenset[str]] = {}
    brands = raw.get("brands") if isinstance(raw, dict) else None
    if isinstance(brands, list):
        for b in brands:
            if not isinstance(b, dict) or not isinstance(b.get("brand_id"), str):
                continue
            doms = b.get("verified_domains") or []
            out[b["brand_id"]] = frozenset(str(d).lower() for d in doms if isinstance(d, str))
    return BrandIndex(out)


@lru_cache(maxsize=4)
def load_brand_index(path: str | None = None) -> BrandIndex:
    p = Path(path) if path else _find_brands_yaml()
    if p is None or not p.is_file():
        return BrandIndex({})
    with p.open(encoding="utf-8") as fh:
        return parse_brands(yaml.safe_load(fh))
