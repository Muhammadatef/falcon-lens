"""url.free_host_or_tunnel evidence and the numeric lexical feature vector for the T1 classifier."""

from __future__ import annotations

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.brands.registry import BrandRegistry
from falcon_core.signals.url.canonical import URL_SHORTENERS, canonicalize, free_host_suffix
from falcon_core.signals.url.common import T1_TIMEOUT_MS, canon, url_evidence
from falcon_core.signals.url.squatting import TYPO_MIN_LABEL
from falcon_core.signals.url.textutil import compact, damerau_osa, entropy

SPEC_FREE = SignalSpec(
    name="url.free_host_or_tunnel",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=("url.free_host_or_tunnel",),
)

RISKY_TLDS = frozenset(
    [
        "xyz",
        "top",
        "icu",
        "click",
        "shop",
        "live",
        "site",
        "online",
        "vip",
        "cfd",
        "sbs",
        "cyou",
        "rest",
        "buzz",
        "monster",
        "work",
        "support",
        "fit",
        "zip",
        "mov",
        "gq",
        "ml",
        "cf",
        "tk",
        "ga",
        "link",
        "life",
        "today",
        "world",
        "bond",
    ]
)

FEATURE_NAMES: tuple[str, ...] = (
    "url_len",
    "host_len",
    "path_len",
    "query_len",
    "num_dots",
    "num_subdomains",
    "num_hyphens_host",
    "digit_ratio_host",
    "digit_ratio_url",
    "host_entropy",
    "label_entropy",
    "longest_label",
    "num_params",
    "path_depth",
    "is_https",
    "is_ip",
    "ip_obfuscated",
    "has_userinfo",
    "nondefault_port",
    "is_punycode",
    "non_ascii_host",
    "mixed_script",
    "num_percent",
    "double_encoded",
    "is_shortener",
    "is_free_host",
    "is_data_uri",
    "tld_len",
    "risky_tld",
    "has_bidi_or_zw",
    "brand_token_in_host",
    "brand_min_edit_distance",
    "is_official",
    "num_special_chars_url",
    "has_at_in_path",
    "has_embedded_url_in_query",
)

SPEC_FEATURES = SignalSpec(
    name="url.lexical_features",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=(),
    feature_names=FEATURE_NAMES,
)


def extract_features(url: str, reg: BrandRegistry | None = None) -> dict[str, float]:
    """Numeric features, all finite floats, fixed key set = FEATURE_NAMES. Never raises."""
    from falcon_core.signals.brands.registry import default_registry

    c = canonicalize(url)
    f = dict.fromkeys(FEATURE_NAMES, 0.0)
    raw = c.raw
    f["url_len"] = float(len(raw))
    f["is_data_uri"] = float(c.is_data_uri)
    f["num_percent"] = float(raw.count("%"))
    f["has_bidi_or_zw"] = float(c.has_bidi or c.has_zero_width)
    f["num_special_chars_url"] = float(
        sum(1 for ch in raw if not ch.isalnum() and ch not in "/.:-_")
    )
    if not c.ok:
        return f
    reg = reg or default_registry()
    host = c.host
    f["host_len"] = float(len(host))
    f["path_len"] = float(len(c.path))
    f["query_len"] = float(len(c.query))
    f["num_dots"] = float(host.count("."))
    f["num_subdomains"] = float(len(c.subdomain_labels))
    f["num_hyphens_host"] = float(host.count("-"))
    f["digit_ratio_host"] = sum(ch.isdigit() for ch in host) / max(len(host), 1)
    f["digit_ratio_url"] = sum(ch.isdigit() for ch in raw) / max(len(raw), 1)
    f["host_entropy"] = entropy(host)
    f["label_entropy"] = entropy(c.domain_label)
    f["longest_label"] = float(max((len(x) for x in c.labels), default=0))
    f["num_params"] = float(len([p for p in c.query.split("&") if p]))
    f["path_depth"] = float(len([p for p in c.path.split("/") if p]))
    f["is_https"] = float(c.scheme == "https")
    f["is_ip"] = float(c.is_ip)
    f["ip_obfuscated"] = float(c.ip_obfuscated)
    f["has_userinfo"] = float(c.userinfo is not None)
    f["nondefault_port"] = float(c.port is not None)
    f["is_punycode"] = float(any(x.startswith("xn--") for x in c.host_ascii.split(".")))
    f["non_ascii_host"] = float(not host.isascii())
    f["mixed_script"] = float(len(c.scripts) > 1)
    f["double_encoded"] = float(c.double_encoded)
    f["is_shortener"] = float(c.registrable in URL_SHORTENERS)
    f["is_free_host"] = float(free_host_suffix(c) is not None)
    f["tld_len"] = float(len(c.suffix.split(".")[-1])) if c.suffix else 0.0
    f["risky_tld"] = float(c.suffix.split(".")[-1] in RISKY_TLDS) if c.suffix else 0.0
    f["has_at_in_path"] = float("@" in c.path)
    f["has_embedded_url_in_query"] = float(
        "http" in c.query_decoded.lower() and "//" in c.query_decoded
    )
    off = reg.is_official(c.registrable)
    f["is_official"] = float(off)
    if not c.is_ip:
        hc = compact(host)
        f["brand_token_in_host"] = float(
            not off and any(len(t) >= 5 and t in hc for b in reg.brands for t in b.tokens_en)
        )
        best = 6
        cand = c.domain_label.replace("-", "")
        for b in reg.brands:
            for label, _s in b.domain_parts:
                if len(label) >= TYPO_MIN_LABEL and not off:
                    best = min(best, damerau_osa(cand, label.replace("-", ""), 5))
        f["brand_min_edit_distance"] = float(best)
    else:
        f["brand_min_edit_distance"] = 6.0
    return f


@signal(SPEC_FREE)
def run_free_host(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not c.ok or c.is_ip:
        return []
    suffix = free_host_suffix(c)
    if suffix is None:
        return []
    tenant = (
        c.domain_label if c.suffix == suffix else c.subdomain.split(".")[-1] if c.subdomain else ""
    )
    return [
        url_evidence(
            "url.free_host_or_tunnel",
            {"suffix": suffix, "tenant": tenant[:100], "psl_private": c.is_private_suffix},
            f"Hosted on a free/shared hosting or tunnel service ({suffix}); judged by the part before it",
            f"الموقع على خدمة استضافة مجانية أو نفق مؤقت ({suffix}) ويُحكم عليه بحسب الجزء الذي يسبقها",
            1.0,
        )
    ]


@signal(SPEC_FEATURES)
def run_features(ctx: SignalContext) -> list[Evidence]:
    """Feature plugin: emits no evidence; the classifier calls ``extract_features`` directly."""
    return []
