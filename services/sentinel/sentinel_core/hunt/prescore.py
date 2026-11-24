"""Hunt queue priority 0..100 (docs/design/HUNTER.md section 3).

THIS IS NOT A RISK SCORE. It only orders candidates and decides which ones may use the visit quota. It never
appears as a score, never reaches the arbiter, and no module under falcon_core.scoring may import it (tested).
All weights are >= 0 (enforced by config.py), so adding a reason never lowers the priority.
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import PrescoreConfig


def prescore(
    cfg: PrescoreConfig,
    *,
    discovery: str,
    permutation_kind: str | None,
    reasons: Iterable[str],
    category: str | None,
) -> int:
    total = cfg.base
    total += cfg.discovery.get(discovery, 0)
    if permutation_kind:
        total += cfg.permutation_kind.get(permutation_kind, 0)
    for r in sorted(set(reasons)):
        total += cfg.reasons.get(r, 0)
    if category:
        total += cfg.category.get(category, 0)
    return max(0, min(100, total))
