"""Helpers shared by the URL plugins."""

from __future__ import annotations

from falcon_core.signals.base import Evidence, SignalContext
from falcon_core.signals.brands.registry import Brand, BrandRegistry, default_registry
from falcon_core.signals.url.canonical import CanonicalURL, canonicalize

T1_TIMEOUT_MS = 50  # pure CPU; each plugin is < 5 ms p95 (tested)


def canon(ctx: SignalContext) -> CanonicalURL:
    return canonicalize(ctx.url or ctx.text or "")


def registry(ctx: SignalContext) -> BrandRegistry:
    r = getattr(ctx, "brands", None)
    return r if isinstance(r, BrandRegistry) else default_registry()


def url_evidence(signal: str, observed: dict[str, object], en: str, ar: str, confidence: float = 1.0) -> Evidence:
    return Evidence(
        signal=signal,
        family="url",
        observed=observed,
        display={"en": en[:200], "ar": ar[:200]},
        confidence=confidence,
    )


def brand_names(b: Brand) -> tuple[str, str]:
    return b.name_en, b.name_ar
