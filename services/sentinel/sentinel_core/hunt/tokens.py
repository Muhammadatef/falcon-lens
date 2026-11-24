"""Brand tokens for Certificate Transparency queries (docs/design/HUNTER.md section 3).

Token = the registrable label of each verified domain, 5+ characters, not a generic service word. Read from the
registry only; no brand name in code. Demo brands are excluded unless asked for (their names exist only on .test).
"""

from __future__ import annotations

from falcon_core.signals.brands.registry import GENERIC_EN, BrandRegistry

TOKEN_MIN_LEN = 5


def brand_tokens(registry: BrandRegistry, *, include_demo: bool = False) -> list[tuple[str, str]]:
    """(brand_id, token) pairs, registry order, de-duplicated on token."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for b in registry.brands:
        if b.is_demo and not include_demo:
            continue
        for label, _suffix in b.domain_parts:
            tok = label.lower()
            if len(tok) < TOKEN_MIN_LEN or tok in GENERIC_EN or tok in seen or not tok.isascii():
                continue
            seen.add(tok)
            out.append((b.brand_id, tok))
    return out


def token_in_name(token: str, name: str) -> bool:
    """True if the brand token appears in the name with hyphens and dots ignored."""
    flat = name.lower().replace("-", "").replace(".", "")
    return token.replace("-", "") in flat
