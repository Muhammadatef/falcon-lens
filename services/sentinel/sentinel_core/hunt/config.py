"""Loads and validates services/sentinel/hunt.yaml (declarative, like rules.yaml)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

DEFAULT_HUNT_PATH = Path(os.environ.get("FL_SENTINEL_HUNT") or Path(__file__).resolve().parents[2] / "hunt.yaml")
SOURCE_KINDS = frozenset({"ct", "permutation", "search", "ads", "maps"})
PERMUTATION_KINDS = ("typo", "homoglyph", "combosquat", "tld_swap")
REASONS = ("resolves_a", "has_mx", "cert_fresh", "brand_token_in_cert")


class HuntConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSpec:
    id: str
    kind: str
    terms_url: str | None
    default_enabled: bool


@dataclass(frozen=True)
class PermutationConfig:
    typo_min_label: int
    cap_per_brand: int
    homoglyphs_per_letter: int
    combo_priority: tuple[str, ...]
    tlds: tuple[str, ...]
    restricted_suffixes: frozenset[str]
    fallback_suffixes: tuple[str, ...]
    keep_suffix_for_demo: bool


@dataclass(frozen=True)
class PrescoreConfig:
    base: int
    discovery: dict[str, int]
    permutation_kind: dict[str, int]
    reasons: dict[str, int]
    category: dict[str, int]
    cert_fresh_days: int


@dataclass(frozen=True)
class HuntConfig:
    sources: dict[str, SourceSpec]
    permutation: PermutationConfig
    prescore: PrescoreConfig


def _weights(d: Any, name: str) -> dict[str, int]:
    if not isinstance(d, dict):
        raise HuntConfigError(f"prescore.{name} must be a mapping")
    out: dict[str, int] = {}
    for k, v in d.items():
        if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 100:
            raise HuntConfigError(f"prescore.{name}.{k}: weights are integers 0..100 (monotone priority)")
        out[str(k)] = v
    return out


def _suffixes(values: Any) -> tuple[str, ...]:
    return tuple(str(t).lower().lstrip(".") for t in values)


def parse(data: dict[str, Any]) -> HuntConfig:
    try:
        sources: dict[str, SourceSpec] = {}
        for sid, s in (data.get("sources") or {}).items():
            if s["kind"] not in SOURCE_KINDS:
                raise HuntConfigError(f"source {sid}: unknown kind {s['kind']}")
            terms = s.get("terms_url")
            if terms is not None and not str(terms).startswith("https://"):
                raise HuntConfigError(f"source {sid}: terms_url must be https or null")
            sources[str(sid)] = SourceSpec(str(sid), s["kind"], terms, bool(s.get("default_enabled", False)))
        p = data["permutation"]
        perm = PermutationConfig(
            typo_min_label=int(p["typo_min_label"]),
            cap_per_brand=int(p["cap_per_brand"]),
            homoglyphs_per_letter=int(p.get("homoglyphs_per_letter", 2)),
            combo_priority=tuple(str(w).lower() for w in p.get("combo_priority", [])),
            tlds=_suffixes(p["tlds"]),
            restricted_suffixes=frozenset(_suffixes(p.get("restricted_suffixes", []))),
            fallback_suffixes=_suffixes(p.get("fallback_suffixes", ["com"])),
            keep_suffix_for_demo=bool(p.get("keep_suffix_for_demo", True)),
        )
        ps = data["prescore"]
        base = ps["base"]
        if not isinstance(base, int) or isinstance(base, bool) or not 0 <= base <= 100:
            raise HuntConfigError("prescore.base must be 0..100")
        pre = PrescoreConfig(
            base=base,
            discovery=_weights(ps.get("discovery", {}), "discovery"),
            permutation_kind=_weights(ps.get("permutation_kind", {}), "permutation_kind"),
            reasons=_weights(ps.get("reasons", {}), "reasons"),
            category=_weights(ps.get("category", {}), "category"),
            cert_fresh_days=int(ps.get("cert_fresh_days", 7)),
        )
    except KeyError as exc:
        raise HuntConfigError(f"hunt.yaml: missing {exc}") from exc
    if perm.cap_per_brand < 1 or perm.typo_min_label < 1:
        raise HuntConfigError("permutation caps must be positive")
    unknown = set(pre.reasons) - set(REASONS)
    if unknown:
        raise HuntConfigError(f"prescore.reasons: unknown {sorted(unknown)}")
    return HuntConfig(sources=sources, permutation=perm, prescore=pre)


def load(path: Path | str = DEFAULT_HUNT_PATH) -> HuntConfig:
    return parse(yaml.safe_load(Path(path).read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def default_config() -> HuntConfig:
    return load()
