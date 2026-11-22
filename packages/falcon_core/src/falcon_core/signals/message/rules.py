# ruff: noqa: E501
"""Rule features over normalised Arabic / English / Arabizi text. Emits spans (offsets), never the text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from falcon_core.signals.message.lexicon import RULES
from falcon_core.signals.message.normalize import Normalized, arabizi_fold, normalize

_AR_PREFIX = "وال|بال|فال|كال|لل|ولل|ال|و|ف|ب|ل|ك"
_AR_SUFFIX = "ات|ون|ين|ان|ها|هم|كم|نا|ه|ك|ي|ا|ت"
MAX_SPANS = 8  # spans reported per rule


@dataclass(frozen=True)
class RuleHit:
    rule: str
    langs: tuple[str, ...]
    spans: tuple[tuple[int, int], ...]  # offsets into the ORIGINAL text
    count: int


def _compile(frags: list[str], lang: str) -> re.Pattern[str]:
    norm = [normalize(f).text for f in frags]
    if lang == "arz":
        norm = [arabizi_fold(f) for f in norm]
    body = "|".join(f"(?:{f})" for f in norm)
    if lang == "ar":
        # Arabic word boundaries: optional attached prefix (و ف ب ل ك ال ...) and suffix (ه ها ك كم ات ...),
        # never a letter on either side, so «العجلة» does not hit an «عجل» term.
        return re.compile(rf"(?<![ء-ي])(?:{_AR_PREFIX})?(?:{body})(?:{_AR_SUFFIX})?(?![ء-ي])")
    return re.compile(rf"(?<![a-z0-9])(?:{body})(?![a-z])")


@lru_cache(maxsize=1)
def _compiled() -> dict[str, list[dict[str, re.Pattern[str]]]]:
    return {
        rule: [{lang: _compile(frags, lang) for lang, frags in group.items()} for group in groups]
        for rule, groups in RULES.items()
    }


def find_rules(text: str) -> list[RuleHit]:
    """Return one RuleHit per rule that fires. Spans are offsets in ``text`` (the original string)."""
    nm: Normalized = normalize(text)
    folded = arabizi_fold(nm.text)
    views = {"ar": nm.text, "en": nm.text, "arz": folded}
    hits: list[RuleHit] = []
    for rule, groups in _compiled().items():
        spans: list[tuple[int, int]] = []
        langs: set[str] = set()
        ok = True
        for group in groups:
            gspans: list[tuple[int, int]] = []
            for lang, pat in group.items():
                for m in pat.finditer(views[lang]):
                    if m.end() > m.start():
                        gspans.append(nm.original_span(m.start(), m.end(), len(text)))
                        langs.add(lang)
            if not gspans:
                ok = False
                break
            spans.extend(gspans)
        if not ok:
            continue
        uniq = sorted(set(spans))
        hits.append(RuleHit(rule, tuple(sorted(langs)), tuple(uniq[:MAX_SPANS]), len(uniq)))
    return hits
