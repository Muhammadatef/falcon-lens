"""Brand references used by the page/visual/brand signals.

Built from ``data/brands.yaml`` entries (parsed by the caller) so this module has no YAML
dependency. ``FIXTURE_BRAND`` is the invented "Falcon Demo Bank" used by fixtures and tests only;
production code must not include it unless a test/eval run asks for it explicitly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..page.text import normalize


@dataclass(frozen=True)
class BrandRef:
    brand_id: str
    name_en: str
    name_ar: str = ""
    verified_domains: tuple[str, ...] = ()
    keywords_en: tuple[str, ...] = ()
    keywords_ar: tuple[str, ...] = ()
    favicon_sha256: tuple[str, ...] = field(default=())
    favicon_phash: tuple[str, ...] = field(default=())

    def name_terms(self) -> tuple[str, ...]:
        """Normalised distinctive names (not the generic keywords like "fine")."""
        terms = [normalize(t).strip() for t in (self.name_en, self.name_ar) if t]
        return tuple(t for t in terms if len(t) >= 4)


def load_brand_refs(entries: Iterable[Mapping[str, Any]]) -> list[BrandRef]:
    out: list[BrandRef] = []
    for e in entries:
        fav = e.get("favicon_hash")
        out.append(
            BrandRef(
                brand_id=str(e["brand_id"]),
                name_en=str(e.get("name_en", "")),
                name_ar=str(e.get("name_ar", "")),
                verified_domains=tuple(str(d).lower() for d in e.get("verified_domains", [])),
                keywords_en=tuple(e.get("keywords_en", [])),
                keywords_ar=tuple(e.get("keywords_ar", [])),
                favicon_phash=(str(fav),) if isinstance(fav, str) and len(fav) == 16 else (),
            )
        )
    return out


#: Invented brand for fixtures. Favicon hashes are filled at test time from the fixture asset.
FIXTURE_BRAND = BrandRef(
    brand_id="falcon_demo_bank",
    name_en="Falcon Demo Bank",
    name_ar="بنك الصقر التجريبي",
    verified_domains=("falcon-demo-bank.test",),
    keywords_en=("falcon demo bank",),
    keywords_ar=("بنك الصقر التجريبي",),
)
