"""visual.* evidence."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from falcon_core.contracts.evidence import Evidence, EvidenceDisplay

from ..page.features import ProfileFeatures
from ..page.hosts import host_of, registrable_domain
from .brands import BrandRef
from .phash import hamming64

FAVICON_PHASH_MAX_DISTANCE = 6  # of 64 bits


def _eid(*parts: str) -> str:
    return "ev_" + hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def favicon_match_evidence(profile: ProfileFeatures, brands: Sequence[BrandRef]) -> list[Evidence]:
    """visual.favicon_match_brand: the page favicon equals (sha256) or resembles (pHash) a known
    brand favicon. Risk only if the page's domain is not one of the brand's verified domains."""
    fav = profile.favicon
    if not (fav.sha256 or fav.phash):
        return []
    site = registrable_domain(host_of(profile.final_url or ""))
    out: list[Evidence] = []
    for b in brands:
        exact = bool(fav.sha256 and fav.sha256 in b.favicon_sha256)
        dist = min((hamming64(fav.phash, h) for h in b.favicon_phash if fav.phash), default=None)
        if not exact and (dist is None or dist > FAVICON_PHASH_MAX_DISTANCE):
            continue
        owned = site in {registrable_domain(d) for d in b.verified_domains}
        out.append(
            Evidence(
                id=_eid("visual.favicon_match_brand", b.brand_id, profile.profile, site),
                signal="visual.favicon_match_brand",
                family="visual",
                observed={
                    "brand_id": b.brand_id,
                    "exact_sha256": exact,
                    "phash_distance": dist,
                    "domain_owned": owned,
                    "profile": profile.profile,
                },
                display=EvidenceDisplay(
                    ar=f"أيقونة الموقع تطابق أيقونة {b.name_ar or b.name_en}",
                    en=f"Site icon matches the {b.name_en} icon",
                ),
                weight=0.0,
                polarity="neutral" if owned else "risk",
                source="sandbox",
                tier="T2",
                confidence=1.0 if exact else max(0.5, 1 - (dist or 0) / 16),
            )
        )
    return out
