"""Cloaking detection: do the mobile-Arabic and desktop-English loads differ materially?"""

from __future__ import annotations

import re

from .features import Cloaking, ProfileFeatures
from .hosts import registrable_domain
from .simhash import hamming_hex
from .text import normalize

SIMHASH_DISTANCE_THRESHOLD = 14  # of 64 bits; benign responsive variants stay well below
TEXT_SIMILARITY_THRESHOLD = 0.35

_WORD = re.compile(r"[0-9a-z؀-ۿ]{3,}")


def _words(text: str) -> set[str]:
    return set(_WORD.findall(normalize(text)))


def text_similarity(a: str, b: str) -> float | None:
    """Jaccard similarity of word sets; ``None`` when either side is too short to judge."""
    wa, wb = _words(a), _words(b)
    if len(wa) < 5 or len(wb) < 5:
        return None
    return len(wa & wb) / len(wa | wb)


def _final_site(p: ProfileFeatures) -> str:
    from .hosts import host_of

    return registrable_domain(host_of(p.final_url or ""))


def compare_profiles(a: ProfileFeatures, b: ProfileFeatures) -> Cloaking:
    """Compare two successfully loaded profiles. Failed loads never count as cloaking."""
    if a.error or b.error or not a.final_url or not b.final_url:
        return Cloaking()
    reasons: list[str] = []
    if _final_site(a) != _final_site(b):
        reasons.append("final_site_differs")
    if a.network.partial or b.network.partial or a.network.truncated != b.network.truncated:
        # One side was read before it finished loading (or cut at the size cap) and the other was not: forms,
        # structure and text then differ only because of HOW MUCH was read, never because the site cloaks.
        return Cloaking(diff="final_site_differs" in reasons, reasons=reasons, inconclusive=True)
    a_cred = any(f.cred_form for f in a.forms)
    b_cred = any(f.cred_form for f in b.forms)
    if a_cred != b_cred:
        reasons.append("cred_form_differs")
    a_exfil = any(t.exfil for t in a.script_post_targets) or any(f.action_exfil for f in a.forms)
    b_exfil = any(t.exfil for t in b.script_post_targets) or any(f.action_exfil for f in b.forms)
    if a_exfil != b_exfil:
        reasons.append("exfil_differs")
    dist: int | None = None
    if a.dom_simhash and b.dom_simhash:
        dist = hamming_hex(a.dom_simhash, b.dom_simhash)
        if dist > SIMHASH_DISTANCE_THRESHOLD:
            reasons.append("dom_structure_differs")
    sim = text_similarity(a.visible_text, b.visible_text)
    if sim is not None and sim < TEXT_SIMILARITY_THRESHOLD:
        reasons.append("text_differs")
    # Structure/text alone can differ for honest responsive sites; require a behavioural reason
    # (site, form or exfil difference) or BOTH structure and text to diverge.
    strong = {"final_site_differs", "cred_form_differs", "exfil_differs"}
    diff = bool(strong & set(reasons)) or {"dom_structure_differs", "text_differs"} <= set(reasons)
    return Cloaking(diff=diff, reasons=reasons if diff else [], simhash_distance=dist, text_similarity=sim)
