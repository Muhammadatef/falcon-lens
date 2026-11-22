"""params.yaml stays in sync with docs/SCORING.md §2, plus the evidence names added after PR #7.

Also covers L1's informational-error decision (feed_disabled / rdap_unsupported_tld) and the
invalid-input degradation from SCORING §2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from falcon_core.scoring import ArbiterContext, load_params, score, template_reasons
from falcon_core.scoring.reasons import load_reporting_channels, template_actions

from scoring_helpers import make_evidence

mk = make_evidence

REPO = Path(__file__).resolve().parents[4]
SCORING_MD = REPO / "docs" / "SCORING.md"
P = load_params()
SIGNAL_RE = re.compile(r"\b[a-z]+\.[a-z_]+(?:\.[a-z_]+)*\b")
NUM_RE = re.compile(r"^\s*([+\-−]?\d+(?:\.\d+)?)")


def _section2_rows() -> list[tuple[str, str]]:
    text = SCORING_MD.read_text(encoding="utf-8")
    start = text.index("## 2.")
    end = text.index("## 3.", start)
    rows: list[tuple[str, str]] = []
    for line in text[start:end].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or cells[0] in ("Signal", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append((cells[0], cells[2]))
    return rows


def _names(cell: str) -> list[str]:
    cell = cell.split("(")[0]  # drop descriptions like "(SPF/DKIM/DMARC fail)"
    names = SIGNAL_RE.findall(cell)
    # "page.js_obfuscation / anti_inspection": bare suffix shares the previous prefix.
    if "/ anti_inspection" in cell:
        names.append("page.anti_inspection")
    return names


def test_section2_parses() -> None:
    rows = _section2_rows()
    assert len(rows) >= 30
    assert any("url.data_uri" in r[0] for r in rows)


@pytest.mark.parametrize("row", _section2_rows(), ids=lambda r: r[0][:40])
def test_every_section2_signal_has_params_entry(row: tuple[str, str]) -> None:
    cell, w_cell = row
    if cell.startswith("domain.age_days"):
        expected = P.domain_age_gt3650 if ">" in cell else P.domain_age_lt30
        assert NUM_RE.match(w_cell) and float(NUM_RE.match(w_cell)[1].replace("−", "-")) == expected  # type: ignore[index]
        return
    if cell.startswith("domain.cert_age_days"):
        assert P.cert_age_lt7 == 0.8
        return
    if cell.startswith("message.rule."):
        assert P.message_rule_weight == 0.6 and P.message_rule_cap == 3.0
        names = re.findall(r"[a-z_]+", cell.split("∈", 1)[1])
        assert set(names) == set(P.message_rule_names)
        return
    names = _names(cell)
    assert names, cell
    m = NUM_RE.match(w_cell)
    assert m, w_cell
    expected = float(m[1].replace("−", "-"))
    for name in names:
        assert name in P.weights, f"{name} listed in SCORING §2 but missing from params.yaml"
        assert P.weights[name] == expected, (name, P.weights[name], expected)


# --- new weights -------------------------------------------------------------------------------


def test_data_uri_weight_feeds_draft_classifier() -> None:
    res = score([mk("url.data_uri")], p_clf=None)
    assert res.weighted_evidence[0].weight == 2.0
    base = score([], p_clf=None)
    assert res.calibrated_probability > base.calibrated_probability
    assert template_reasons(res, "en")[0].key == "reasons.url.data_uri"


def test_message_brand_weights() -> None:
    ctx = ArbiterContext(input_type="message")
    res = score([mk("message.brand_mention"), mk("message.brand_url_mismatch")], 0.2, ctx)
    assert [e.weight for e in res.weighted_evidence] == [0.5, 1.0]


@pytest.mark.parametrize(
    "signal",
    [
        "message.contains_url",
        "message.contains_phone",
        "message.link_verdict",
        "email.link_verdict",
        "email.return_path_mismatch",
        "image.qr_decoded",
    ],
)
def test_informational_signals_do_not_move_p(signal: str) -> None:
    res = score([mk(signal, {"value": "x"})], p_clf=0.3, ctx=ArbiterContext(input_type="message"))
    assert res.weighted_evidence[0].weight == 0.0
    assert res.calibrated_probability == 0.3
    assert not res.degraded


@pytest.mark.parametrize(
    ("observed", "weight"),
    [
        ({"detected_type": "pdf", "risky": False}, 0.0),
        ({"detected_type": "exe", "risky": True}, 1.5),
        ({"detected_type": "lnk", "risky": False}, 1.5),
        ({"detected_type": "zip", "risky": True, "double_extension": True}, 1.5),
    ],
)
def test_email_attachment_weight(observed: dict[str, object], weight: float) -> None:
    res = score([mk("email.attachment", observed)], 0.2, ArbiterContext(input_type="email"))
    assert res.weighted_evidence[0].weight == weight


@pytest.mark.parametrize("signal", ["email.invalid", "image.invalid"])
def test_invalid_input_sets_degraded(signal: str) -> None:
    ev = mk(signal, {"reason": "too_large"})
    res = score([ev], p_clf=0.01, ctx=ArbiterContext(input_type=signal.split(".")[0]))  # type: ignore[arg-type]
    assert res.degraded and res.verdict == "suspicious"
    assert res.degraded_reasons == (f"invalid_input:{signal}",)
    assert res.weighted_evidence[0].weight == 0.0
    reasons = template_reasons(res, "en")
    assert reasons[0].key == "degraded.degraded" and reasons[0].evidence_ids == (ev.id,)


# --- informational errors (L1 decision) ------------------------------------------------------


@pytest.mark.parametrize(
    ("signal", "error", "source"),
    [
        ("rep.gsb", "feed_disabled", "gsb"),
        ("rep.urlhaus", "feed_disabled", "urlhaus"),
        ("rep.openphish", "feed_disabled", "openphish"),
        ("domain.age", "rdap_unsupported_tld", "rdap"),
    ],
)
def test_informational_errors_do_not_degrade(signal: str, error: str, source: str) -> None:
    ev = mk(signal, None, error=error, source=source, confidence=0.0)
    res = score([ev], p_clf=0.01)
    assert res.degraded is False
    assert res.verdict == "no_warning_signs"
    assert res.weighted_evidence[0].weight == 0.0
    assert res.errored_evidence_ids == ()
    assert template_reasons(res, "en") == []


def test_real_errors_still_degrade_next_to_informational_ones() -> None:
    ev = [
        mk("rep.gsb", None, error="feed_disabled"),
        mk("domain.age", None, error="rdap_unsupported_tld"),
        mk("domain.cert_age", None, error="timeout"),
    ]
    res = score(ev, p_clf=0.01)
    assert res.degraded and res.degraded_reasons == ("signal_error:domain.cert_age",)
    assert res.errored_evidence_ids == (ev[2].id,)


# --- reporting channels are shown as-is (L1: invariant 5 exempts them) -----------------------


def test_official_reporting_channels_are_not_defanged() -> None:
    import yaml

    cfg_path = REPO / "config" / "reporting_channels.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    report = template_actions("dangerous", load_reporting_channels(str(cfg_path)))["report"]
    shown = [c["value"] for c in report["channels"]]  # type: ignore[index]
    assert shown == [c["value"] for c in cfg["channels"]]
    for value in shown:
        assert "[.]" not in value and "hxxp" not in value
