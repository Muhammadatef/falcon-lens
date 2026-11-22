"""Visual helpers: perceptual hashes. Evidence is built by ``falcon_core.cascade.page``."""

from .phash import hamming64, phash_from_gray32

__all__ = ["hamming64", "phash_from_gray32"]
