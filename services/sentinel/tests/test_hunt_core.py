"""Hunt mode deterministic core (T-033): permute, tokens, prescore, candidates, hunt.yaml, migration."""

from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sentinel_core.hunt import candidates as cmod
from sentinel_core.hunt import config, permute, prescore, tokens

from falcon_core.signals.brands.registry import BrandRegistry, default_registry

ROOT = Path(__file__).resolve().parents[3]
HUNT_DIR = ROOT / "services" / "sentinel" / "sentinel_core" / "hunt"
CFG = config.default_config()
T0 = datetime(2026, 11, 24, 20, 0, tzinfo=UTC)


def _brand(bid: str) -> object:
    return next(b for b in default_registry().brands if b.brand_id == bid)


def _demo() -> list[permute.Permutation]:
    reg = default_registry()
    return permute.permute_brand(_brand("falcon_demo_bank"), reg, CFG.permutation)  # type: ignore[arg-type]


# ---------------------------------------------------------------- permute


def test_demo_brand_has_every_kind() -> None:
    out = _demo()
    kinds = {p.kind for p in out}
    assert kinds == {"typo", "homoglyph", "combosquat", "tld_swap"}
    names = {p.name for p in out}
    for w in ("secure", "login", "pay", "update", "fine", "refund"):
        assert any(w in n and p.kind == "combosquat" for p in out for n in [p.name]), w
        assert f"falcon-demo-bank-{w}.test" in names
    homo = [p.name for p in out if p.kind == "homoglyph"]
    assert homo and all(n.startswith("xn--") for n in homo)
    assert all(n.isascii() for n in names)
    assert "falcon-demo-bank.com" in names  # TLD swap
    assert "falcon-demo-bnak.test" in names  # transposition


def test_deterministic_and_capped() -> None:
    a, b = _demo(), _demo()
    assert a == b
    assert len(a) <= CFG.permutation.cap_per_brand
    small = replace(CFG.permutation, cap_per_brand=8)
    out = permute.permute_brand(_brand("falcon_demo_bank"), default_registry(), small)  # type: ignore[arg-type]
    assert len(out) == 8
    assert {p.kind for p in out} == {"typo", "homoglyph", "combosquat", "tld_swap"}  # interleaved, no starvation


def test_never_a_verified_domain_of_any_brand() -> None:
    reg = default_registry()
    out = permute.permute_registry(reg, CFG.permutation)
    official = {d for b in reg.brands for d in b.verified_domains}
    assert out
    assert not [p.name for p in out if cmod.registrable(p.name) in official]
    assert len({p.name for p in out}) == len(out)


def test_cross_brand_official_dropped() -> None:
    # A typo of brand A that is brand B's verified domain must never be generated.
    reg = BrandRegistry.from_entries(
        [
            {"brand_id": "a", "name_en": "A", "category": "demo", "verified_domains": ["examplebank.test"]},
            {"brand_id": "b", "name_en": "B", "category": "demo", "verified_domains": ["exampleban.test"]},
        ]
    )
    names = {p.name for p in permute.permute_brand(reg.brands[0], reg, CFG.permutation)}
    assert "exampleban.test" not in names
    assert "examplebnk.test" in names


@pytest.mark.parametrize("label", ["du", "rta", "moi", "dib"])
def test_short_label_combosquats_only(label: str) -> None:
    reg = BrandRegistry.from_entries(
        [{"brand_id": "s", "name_en": "S", "category": "bank", "verified_domains": [f"{label}.ae"]}]
    )
    out = permute.permute_brand(reg.brands[0], reg, CFG.permutation)
    kinds = {p.kind for p in out}
    assert "typo" not in kinds and "homoglyph" not in kinds
    assert "combosquat" in kinds


def test_restricted_suffix_goes_to_fallback() -> None:
    reg = BrandRegistry.from_entries(
        [{"brand_id": "g", "name_en": "G", "category": "police", "verified_domains": ["sampleauth.gov.ae"]}]
    )
    out = permute.permute_brand(reg.brands[0], reg, CFG.permutation)
    assert out and not [p.name for p in out if p.name.endswith(".gov.ae")]
    assert "sampleauth-secure.ae" in {p.name for p in out}


def test_all_labels_valid_dns() -> None:
    for p in permute.permute_registry(default_registry(), CFG.permutation):
        for lab in p.name.split("."):
            assert 1 <= len(lab) <= 63 and not lab.startswith("-") and not lab.endswith("-"), p.name
            assert re.fullmatch(r"[a-z0-9-]+", lab), p.name


def test_no_brand_names_in_hunt_code() -> None:
    out = subprocess.run(  # noqa: S603
        ["grep", "-rnE", "adpolice|uaepass|tamm|emiratespost", str(HUNT_DIR)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.stdout == ""


# ---------------------------------------------------------------- tokens


def test_tokens_from_registry() -> None:
    toks = tokens.brand_tokens(default_registry())
    words = [t for _b, t in toks]
    assert words and all(len(t) >= 5 for t in words)
    assert len(words) == len(set(words))
    assert "falcon-demo-bank" not in words  # demo excluded by default
    assert ("falcon_demo_bank", "falcon-demo-bank") in tokens.brand_tokens(default_registry(), include_demo=True)
    assert "du" not in words and "rta" not in words
    assert tokens.token_in_name("falcon-demo-bank", "login.falcondemobank-secure.test")


def test_tokens_drop_generic_words() -> None:
    reg = BrandRegistry.from_entries(
        [{"brand_id": "x", "name_en": "X", "category": "bank", "verified_domains": ["refund.test", "parking.test"]}]
    )
    assert tokens.brand_tokens(reg) == []


# ---------------------------------------------------------------- prescore

REASONS = ["resolves_a", "has_mx", "cert_fresh", "brand_token_in_cert"]


@pytest.mark.parametrize("disc", ["ct", "permutation"])
@pytest.mark.parametrize("kind", [None, "typo", "homoglyph", "combosquat", "tld_swap"])
def test_prescore_monotone(disc: str, kind: str | None) -> None:
    import itertools

    for n in range(len(REASONS) + 1):
        for subset in itertools.combinations(REASONS, n):
            s = prescore.prescore(CFG.prescore, discovery=disc, permutation_kind=kind, reasons=subset, category="bank")
            assert 0 <= s <= 100
            for extra in REASONS:
                more = prescore.prescore(
                    CFG.prescore, discovery=disc, permutation_kind=kind, reasons=(*subset, extra), category="bank"
                )
                assert more >= s


def test_prescore_negative_weight_rejected() -> None:
    raw = {
        "permutation": {"typo_min_label": 5, "cap_per_brand": 10, "tlds": ["com"]},
        "prescore": {"base": 10, "reasons": {"has_mx": -5}},
    }
    with pytest.raises(config.HuntConfigError):
        config.parse(raw)


def test_prescore_not_imported_by_scoring() -> None:
    scoring = ROOT / "packages" / "falcon_core" / "src" / "falcon_core" / "scoring"
    worker = ROOT / "services" / "worker"
    for path in [*scoring.rglob("*.py"), *worker.rglob("*.py")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods = [node.module or ""]
            assert not [m for m in mods if "hunt" in m or "prescore" in m], path


# ---------------------------------------------------------------- candidates


def _cand(domain: str = "falcon-demo-bank-secure.test", **kw: object) -> cmod.Candidate:
    base: dict[str, object] = {
        "domain": domain,
        "brand_id": "falcon_demo_bank",
        "discovery": "permutation",
        "permutation_kind": "combosquat",
        "first_seen": T0,
        "provenance": {"source_id": "fixture", "terms_url": None, "retrieved_at": T0, "source": "fixture"},
        "reasons": ("permutation:combosquat",),
        "prescore": 50,
    }
    base.update(kw)
    return cmod.Candidate(**base)  # type: ignore[arg-type]


def test_candidate_id_deterministic() -> None:
    a, b = _cand(), _cand()
    assert a.candidate_id == b.candidate_id and a.candidate_id.startswith("hc_")
    assert _cand(domain="other-falcon-demo-bank.test").candidate_id != a.candidate_id


def test_dedupe_on_registrable_domain() -> None:
    a = _cand(
        domain="login.falcon-demo-bank-secure.test",
        first_seen=T0 + timedelta(minutes=5),
        reasons=("resolves_a",),
        prescore=70,
    )
    b = _cand(first_seen=T0, upstream_seen=T0 - timedelta(days=1))
    c = _cand(domain="falcon-demo-bank-pay.test")
    out = cmod.dedupe([a, b, c])
    assert [x.domain for x in out] == ["falcon-demo-bank-secure.test", "falcon-demo-bank-pay.test"]
    first = out[0]
    assert first.first_seen == T0 and first.prescore == 70
    assert set(first.reasons) == {"resolves_a", "permutation:combosquat"}
    assert first.upstream_seen == T0 - timedelta(days=1)
    assert first.candidate_id == cmod.candidate_id("falcon-demo-bank-secure.test", T0)


def test_transitions() -> None:
    c = _cand()
    c = cmod.transition(c, "queued")
    c = cmod.transition(c, "submitted", verdict_id="vd_x")
    with pytest.raises(cmod.TransitionError):
        cmod.transition(c, "new")
    done = cmod.apply_verdict(c, "vd_x", "dangerous", T0 + timedelta(minutes=2))
    assert done.status == "confirmed" and done.verdict == "dangerous"
    assert done.time_to_detection_s is None and done.time_to_detection_basis is None  # no upstream basis
    cleared = cmod.apply_verdict(c, "vd_x", "no_warning_signs", T0)
    assert cleared.status == "cleared"
    known = cmod.transition(cmod.transition(_cand(), "queued"), "already_known")
    assert cmod.apply_verdict(known, "vd_y", "dangerous", T0).status == "already_known"  # terminal
    with pytest.raises(cmod.TransitionError):
        cmod.transition(known, "confirmed")


def test_time_to_detection_basis() -> None:
    v = T0 + timedelta(hours=1)
    assert cmod.time_to_detection(v, T0, None) == (3600.0, "cert_not_before")
    assert cmod.time_to_detection(v, T0, T0 - timedelta(hours=1)) == (7200.0, "rdap")
    assert cmod.time_to_detection(v, None, None) == (None, None)
    assert cmod.time_to_detection(T0, v, None) == (0.0, "cert_not_before")  # backdated certs never go negative


def test_contract_projection_defanged() -> None:
    doc = cmod.to_contract(_cand(upstream_seen=T0))
    assert doc["domain_defanged"] == "falcon-demo-bank-secure[.]test"
    assert "falcon-demo-bank-secure.test" not in str(doc)
    assert len(doc["domain_sha256"]) == 64
    assert doc["provenance"]["retrieved_at"] == "2026-11-24T20:00:00Z"


# ---------------------------------------------------------------- config + migration


def test_hunt_yaml_defaults() -> None:
    s = CFG.sources
    assert s["ct_search"].default_enabled is False
    assert s["fixture"].default_enabled is False
    for k in ("search", "ads", "maps"):
        assert s[k].default_enabled is False
    assert s["permutation"].default_enabled and not s["ct_lookup"].default_enabled


def test_migration_declares_tables() -> None:
    sql = (ROOT / "services" / "sentinel" / "migrations" / "002_hunt.sql").read_text()
    for t in ("hunt_candidates", "hunt_source_state", "hunt_quota", "hunt_cycles"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql
    for st in cmod.STATUSES:
        assert f"'{st}'" in sql


def test_hunt_core_has_no_io() -> None:
    banned = {"httpx", "socket", "requests", "redis", "psycopg", "urllib.request", "asyncio"}
    for path in HUNT_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & banned, path
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in banned, path
