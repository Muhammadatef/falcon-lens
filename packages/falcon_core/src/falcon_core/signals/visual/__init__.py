"""Visual signals: favicon / screenshot perceptual hashes and brand matching."""

from .brands import FIXTURE_BRAND, BrandRef, load_brand_refs
from .evidence import favicon_match_evidence
from .phash import hamming64, phash_from_gray32

__all__ = [
    "FIXTURE_BRAND",
    "BrandRef",
    "favicon_match_evidence",
    "hamming64",
    "load_brand_refs",
    "phash_from_gray32",
]
