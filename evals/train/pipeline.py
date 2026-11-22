"""Offline T0/T1 pipeline pieces shared by training and the eval harness (no network, no LLM).

For one URL: T1 url signals (``falcon_core.signals``) -> evidence, lexical features -> calibrated ``p_clf``,
registry lookup -> ``registry.verified_official`` evidence (what the cascade's T0 registry step emits), then the
deterministic arbiter. Tiers above T1 (sandbox render, LLM) are not run here and are reported ``not_evaluated``.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from evals.common import registrable_domain
from falcon_core.scoring.arbiter import ArbiterContext, ArbiterResult, has_brand_conflict, score
from falcon_core.scoring.evidence import Evidence, from_contract
from falcon_core.scoring.params import ScoringParams
from falcon_core.signals import REGISTRY
from falcon_core.signals.brands.registry import default_registry
from falcon_core.signals.url.lexical import FEATURE_NAMES, extract_features


@dataclass
class _Ctx:
    url: str | None = None
    text: str | None = None
    input_type: str = "url"
    http: Any = None
    cache: Any = None
    mirror: Any = None
    clock: Any = None
    brands: Any = None


# Feature groups for the ablation (all are the "url" signal family; the groups are finer than the family).
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "length_structure": (
        "url_len",
        "host_len",
        "path_len",
        "query_len",
        "num_dots",
        "num_subdomains",
        "num_params",
        "path_depth",
        "longest_label",
    ),  # fmt: skip
    "char_statistics": (
        "num_hyphens_host",
        "digit_ratio_host",
        "digit_ratio_url",
        "host_entropy",
        "label_entropy",
        "num_percent",
        "num_special_chars_url",
    ),  # fmt: skip
    "scheme_host_tricks": (
        "is_https",
        "is_ip",
        "ip_obfuscated",
        "has_userinfo",
        "nondefault_port",
        "is_punycode",
        "non_ascii_host",
        "mixed_script",
        "double_encoded",
        "is_data_uri",
        "has_bidi_or_zw",
        "has_at_in_path",
        "has_embedded_url_in_query",
    ),  # fmt: skip
    "tld_hosting": ("tld_len", "risky_tld", "is_shortener", "is_free_host"),
    "brand_registry": ("brand_token_in_host", "brand_min_edit_distance", "is_official"),
}


def feature_vector(url: str) -> list[float]:
    f = extract_features(url)
    return [f[n] for n in FEATURE_NAMES]


def feature_matrix(urls: list[str]) -> Any:
    return np.array([feature_vector(u) for u in urls], dtype=float)


def t1_evidence(url: str) -> list[Evidence]:
    """Run every registered T1 url signal synchronously (offline) and convert to the arbiter's Evidence."""
    ctx = _Ctx(url=url)
    out: list[Evidence] = []
    for name in sorted(REGISTRY):
        spec, fn = REGISTRY[name]
        if spec.tier != "T1" or spec.family != "url" or "url" not in spec.input_types:
            continue
        for ev in fn.sync(ctx):  # type: ignore[attr-defined]
            out.append(from_contract(ev.to_dict()))
    return out


def verified_domains() -> dict[str, frozenset[str]]:
    return {b.brand_id: frozenset(b.verified_domains) for b in default_registry().brands}


def registry_evidence(domain: str) -> list[Evidence]:
    brand = default_registry().official_brand(domain)
    if brand is None:
        return []
    return [
        Evidence(
            id="ev_registry_" + domain,
            signal="registry.verified_official",
            family="brand",
            observed={"brand_id": brand.brand_id, "domain": domain},
            source="computed",
            tier="T0",
            polarity="trust",
        )
    ]


@dataclass
class Scored:
    result: ArbiterResult
    p_clf: float
    brand_conflict: bool
    latency_ms: float
    stage_ms: dict[str, float] = field(default_factory=dict)


def score_url(url: str, p_clf: float, params: ScoringParams, with_registry: bool = True) -> Scored:
    """Arbiter result for one URL given its (calibrated) classifier probability."""
    t0 = time.perf_counter()
    ev = t1_evidence(url)
    t1 = time.perf_counter()
    dom = registrable_domain(url)
    if with_registry:
        ev = [*ev, *registry_evidence(dom)]
    ctx = ArbiterContext(
        input_type="url",
        registrable_domain=dom,
        verified_domains=verified_domains() if with_registry else None,
        params=params,
    )
    res = score(ev, p_clf=min(max(p_clf, 0.0), 1.0), ctx=ctx)
    t2 = time.perf_counter()
    return Scored(
        result=res,
        p_clf=p_clf,
        brand_conflict=has_brand_conflict(ev),
        latency_ms=(t2 - t0) * 1000,
        stage_ms={"signals": (t1 - t0) * 1000, "arbiter": (t2 - t1) * 1000},
    )


def run_async_signals(url: str) -> list[Evidence]:
    """The production (async, timeout-enforced) path; used by a test to prove it equals the sync path."""
    ctx = _Ctx(url=url)
    out: list[Evidence] = []
    for name in sorted(REGISTRY):
        spec, fn = REGISTRY[name]
        if spec.tier == "T1" and spec.family == "url" and "url" in spec.input_types:
            out.extend(from_contract(e.to_dict()) for e in asyncio.run(fn(ctx)))
    return out
