"""UAE lure fragments (lexicon.UAE_LURES): merge helper and flag. Generic roles only; no real brand in fixtures."""

from __future__ import annotations

import copy

import pytest

from falcon_core.signals.message import lexicon
from falcon_core.signals.message.intent_lexicon import UAE_INTENT_LURES
from falcon_core.signals.message.rules import find_rules


def merged() -> dict[str, list[lexicon.Group]]:
    rules = copy.deepcopy(lexicon.RULES)
    lexicon.merge_lures(rules, lexicon.UAE_LURES)
    return rules


def names(text: str, rules: dict[str, list[lexicon.Group]]) -> set[str]:
    return {h.rule for h in find_rules(text, rules)}


def test_merge_is_idempotent_and_only_appends() -> None:
    rules = merged()
    again = copy.deepcopy(rules)
    lexicon.merge_lures(again, lexicon.UAE_LURES)
    assert again == rules
    for name, groups in lexicon.RULES.items():
        for g_old, g_new in zip(groups, rules[name], strict=True):
            for lang, frags in g_old.items():
                assert g_new[lang][: len(frags)] == frags


def test_toll_fine_and_settle_ask() -> None:
    t = "You have unpaid toll charges. Settle now to avoid a penalty."
    assert {"fine", "payment"} <= names(t, merged())


def test_customs_parcel() -> None:
    assert "delivery_fee" in names("Your parcel is on hold at customs, customs duty is due.", merged())


def test_identity_authority_claims() -> None:
    assert "authority" in names("ICP notice: identity and citizenship record update", merged())
    assert "authority" in names("تنبيه من الهوية الرقمية", merged())


def test_plain_notices_stay_quiet() -> None:
    for t in ["Your parcel is out for delivery today.", "Your one-time code is XXXXXX. Never share it."]:
        assert not names(t, merged()) & {"fine", "payment", "delivery_fee", "authority"}


def test_lure_targets_exist() -> None:
    from falcon_core.signals.message.intent_lexicon import FEATURES

    for rule, idx, _lang, _frags in lexicon.UAE_LURES:
        assert idx < len(lexicon.RULES[rule])
    for feat, idx, _lang, _frags in UAE_INTENT_LURES:
        assert idx < len(FEATURES[feat])


def test_flag_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    for v, want in [("1", True), ("true", True), ("0", False), ("", False), ("no", False)]:
        monkeypatch.setenv("FL_UAE_LURES", v)
        assert lexicon.uae_lures_enabled() is want
