"""Bilingual template catalogs (``ar.yaml`` written natively, ``en.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast

import yaml

Lang = Literal["ar", "en"]
LANGS: tuple[Lang, ...] = ("ar", "en")
CATALOG_DIR = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class Catalog:
    lang: Lang
    verdict: dict[str, str]
    degraded: str
    hard_rules: dict[str, str]
    reasons: dict[str, str]
    actions: dict[str, dict[str, list[str]]]
    caution: list[str]
    report: dict[str, str]


def _str_map(raw: object, where: str) -> dict[str, str]:
    if not isinstance(raw, dict) or not all(isinstance(v, str) for v in raw.values()):
        raise TypeError(f"i18n: '{where}' must map to strings")
    return {str(k): v for k, v in cast(dict[object, str], raw).items()}


def _str_list(raw: object, where: str) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise TypeError(f"i18n: '{where}' must be a list of strings")
    return list(cast(list[str], raw))


@lru_cache(maxsize=4)
def load_catalog(lang: Lang) -> Catalog:
    if lang not in LANGS:
        raise ValueError(f"unsupported language: {lang}")
    with open(CATALOG_DIR / f"{lang}.yaml", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise TypeError(f"i18n/{lang}.yaml: expected a mapping")
    data = cast(dict[str, object], raw)
    actions_raw = data.get("actions")
    if not isinstance(actions_raw, dict):
        raise TypeError("i18n: 'actions' missing")
    actions: dict[str, dict[str, list[str]]] = {}
    for verdict, block in cast(dict[str, object], actions_raw).items():
        if not isinstance(block, dict):
            raise TypeError(f"i18n: actions.{verdict} must be a mapping")
        b = cast(dict[str, object], block)
        actions[verdict] = {
            k: _str_list(b.get(k), f"actions.{verdict}.{k}") for k in ("now", "if_already_acted")
        }
    degraded = data.get("degraded")
    if not isinstance(degraded, str):
        raise TypeError("i18n: 'degraded' must be a string")
    return Catalog(
        lang=lang,
        verdict=_str_map(data.get("verdict"), "verdict"),
        degraded=degraded,
        hard_rules=_str_map(data.get("hard_rules"), "hard_rules"),
        reasons=_str_map(data.get("reasons"), "reasons"),
        actions=actions,
        caution=_str_list(data.get("caution"), "caution"),
        report=_str_map(data.get("report"), "report"),
    )
