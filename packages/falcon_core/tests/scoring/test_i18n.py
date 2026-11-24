"""i18n catalogs: no forbidden words, key parity, phone-length lines, full template coverage."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from falcon_core import i18n
from falcon_core.i18n import load_catalog
from falcon_core.scoring import load_params
from falcon_core.scoring.reasons import all_template_keys

# voice_script.yaml is the spoken-line script for the voice assistant (its own tests live in web/), not a UI catalog.
CATALOG_FILES = sorted(p for p in Path(i18n.__file__).parent.glob("*.yaml") if p.name != "voice_script.yaml")
# "safe" in any case, and the Arabic word for it with or without the madda.
FORBIDDEN = [
    re.compile(r"safe", re.IGNORECASE),
    re.compile("\u0622\u0645\u0646"),  # alef-madda, meem, noon (and every inflection built on it)
    # the same word written without the madda, as a standalone word
    re.compile("(?<![\u0600-\u06ff])\u0627\u0645\u0646(?:\u0629|\u0647)?(?![\u0600-\u06ff])"),
]


def _strings(cat: i18n.Catalog) -> list[str]:
    out = [
        cat.degraded,
        *cat.verdict.values(),
        *cat.hard_rules.values(),
        *cat.reasons.values(),
        *cat.caution,
        *cat.report.values(),
    ]
    for block in cat.actions.values():
        for items in block.values():
            out += items
    return out


def test_catalog_files_exist() -> None:
    assert {p.name for p in CATALOG_FILES} == {"ar.yaml", "en.yaml"}


@pytest.mark.parametrize("path", CATALOG_FILES, ids=lambda p: p.name)
def test_no_forbidden_words_anywhere_in_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for pat in FORBIDDEN:
        assert not pat.search(text), f"{path.name}: forbidden word matched {pat.pattern}"


@pytest.mark.parametrize("lang", ["ar", "en"])
def test_lengths_fit_contract_and_phone(lang: str) -> None:
    cat = load_catalog(lang)
    for s in [*cat.hard_rules.values(), *cat.reasons.values(), cat.degraded]:
        assert 0 < len(s) <= 120, s  # contract allows 220; phone screen wants short
    for block in cat.actions.values():
        for items in block.values():
            assert 1 <= len(items) <= 6
            assert all(0 < len(s) <= 160 for s in items)
    assert 1 <= len(cat.caution) <= 6 and all(len(s) <= 160 for s in cat.caution)


def test_key_parity_between_languages() -> None:
    ar, en = load_catalog("ar"), load_catalog("en")
    assert ar.reasons.keys() == en.reasons.keys()
    assert (
        ar.hard_rules.keys() == en.hard_rules.keys() == {"H1", "H2", "H3", "H4", "H5", "H5s", "H6", "RF1", "RF2", "RF3"}
    )
    assert ar.verdict.keys() == en.verdict.keys() == {"dangerous", "suspicious", "no_warning_signs"}
    assert ar.actions.keys() == en.actions.keys() == {"dangerous", "suspicious", "no_warning_signs"}
    assert ar.report.keys() == en.report.keys() == {"with_channels", "generic"}


def test_arabic_is_arabic() -> None:
    ar = load_catalog("ar")
    for s in _strings(ar):
        assert re.search(r"[؀-ۿ]", s), s


def test_required_wording() -> None:
    assert load_catalog("ar").verdict["no_warning_signs"] == "لم نجد علامات تحذير"
    assert load_catalog("en").verdict["no_warning_signs"] == "No warning signs found"
    assert load_catalog("ar").degraded == "لم نتمكن من إكمال كل الفحوصات."


def test_every_weighted_signal_has_a_template() -> None:
    p = load_params()
    # Informational (weight 0) signals never become reasons, so they need no template;
    # email.attachment carries a conditional weight (risky attachments).
    signals = [
        *(s for s, w in p.weights.items() if w != 0.0),
        "email.attachment",
        *(f"message.rule.{n}" for n in p.message_rule_names),
        "domain.age",
        "domain.cert_age",
    ]
    for lang in ("ar", "en"):
        cat = load_catalog(lang)
        missing = [k for k in all_template_keys(signals) if k not in cat.reasons]
        assert not missing, (lang, missing)


def test_no_request_for_personal_details() -> None:
    # Templates must never ask the user to send us personal, banking or ID details.
    en = load_catalog("en")
    for s in _strings(en):
        assert not re.search(r"\b(send|share|enter|give) (us|me)\b", s, re.IGNORECASE), s
