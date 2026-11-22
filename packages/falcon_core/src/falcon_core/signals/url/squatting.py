"""url.typosquat, url.combosquat, url.brand_in_subdomain_or_path (all offline, against data/brands.yaml)."""

from __future__ import annotations

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.brands.registry import Brand, BrandRegistry
from falcon_core.signals.url.canonical import CanonicalURL
from falcon_core.signals.url.common import T1_TIMEOUT_MS, canon, registry, url_evidence
from falcon_core.signals.url.textutil import all_subs_adjacent, compact, damerau_osa, normalize_arabic

# English + transliterated-Arabic action/service words that scammers glue onto a brand name.
COMBO_EN = (
    "pay",
    "payment",
    "secure",
    "security",
    "track",
    "tracking",
    "verify",
    "verification",
    "update",
    "login",
    "signin",
    "logon",
    "fine",
    "fines",
    "bill",
    "refund",
    "claim",
    "account",
    "support",
    "help",
    "portal",
    "online",
    "service",
    "services",
    "customs",
    "delivery",
    "parcel",
    "renew",
    "recharge",
    "confirm",
    "unlock",
    "suspend",
    "otp",
    "kyc",
    "wallet",
    "reward",
    "rewards",
    "gift",
    "violation",
    "violations",
    "traffic",
    "official",
    "gov",
    "appeal",
    "clearance",
    "invoice",
)
COMBO_TRANSLIT = (
    "mukhalafa",
    "mukhalafat",
    "mokhalafa",
    "mokhalafat",
    "mokhalfat",
    "mukhalfat",
    "tahdeeth",
    "tahdith",
    "tahqeeq",
    "tahaqoq",
    "sadad",
    "dafaa",
    "daf3",
    "fatoora",
    "fatura",
    "fatoura",
    "tajdeed",
    "tajdid",
    "shahn",
    "raseed",
    "rasid",
    "hesab",
    "hisab",
    "khidma",
    "khedmat",
    "khadamat",
    "balagh",
    "tawseel",
    "tawsil",
    "tatbeeq",
)
COMBO_AR = tuple(
    normalize_arabic(w)
    for w in "دفع سداد تحقق تحديث تتبع مخالفة مخالفات تجديد استرداد حساب فاتورة خدمات رسمي موقع بوابة شحن توصيل".split()
)
_COMBO_ALL = COMBO_EN + COMBO_TRANSLIT

TYPO_MIN_LABEL = 5  # shorter brand labels (du, moi, rta, dib, adcb...) are matched exactly only


def _max_distance(n: int) -> int:
    return 2 if n >= 8 else 1


def _has_combo(rem: str) -> str | None:
    for w in _COMBO_ALL:
        if len(w) >= 3 and w in rem:
            return w
    for w in COMBO_AR:
        if w in rem:
            return w
    return None


# ---------------------------------------------------------------- typosquat
SPEC_TYPO = SignalSpec(
    name="url.typosquat",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=("url.typosquat",),
)


def typosquat_match(c: CanonicalURL, reg: BrandRegistry) -> dict[str, object] | None:
    cand = c.domain_label
    if len(cand) < 4 or not c.ok or c.is_ip:
        return None
    cand_n = cand.replace("-", "")
    best: tuple[int, dict[str, object]] | None = None
    for b in reg.brands:
        for label, suffix in b.domain_parts:
            if len(label) < TYPO_MIN_LABEL:
                continue
            label_n = label.replace("-", "")
            info: dict[str, object] | None = None
            d: int
            if cand == label:
                if c.suffix != suffix and not c.is_private_suffix:
                    d, info = 1, {"kind": "tld_swap", "distance": 0}
                else:
                    continue
            elif cand_n == label_n:
                d, info = 1, {"kind": "hyphenation", "distance": 0}
            else:
                lim = _max_distance(len(label_n))
                d = damerau_osa(cand_n, label_n, 2)
                if d <= lim or d == 2 and all_subs_adjacent(cand_n, label_n):
                    info = {"kind": "edit_distance", "distance": d}
                if info is not None:
                    info["keyboard_adjacent"] = all_subs_adjacent(cand_n, label_n) or (
                        d == 1 and len(cand_n) == len(label_n) and all_subs_adjacent(cand_n, label_n)
                    )
                    d = d * 2
            if info is None:
                continue
            info.update(brand_id=b.brand_id, target=f"{label}.{suffix}".replace(".", "[.]"), label=cand[:100])
            if best is None or d < best[0]:
                best = (d, info)
    return best[1] if best else None


@signal(SPEC_TYPO)
def run_typo(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    reg = registry(ctx)
    if not c.ok or c.is_ip or reg.is_official(c.registrable):
        return []
    m = typosquat_match(c, reg)
    if not m:
        return []
    brand = next(b for b in reg.brands if b.brand_id == m["brand_id"])
    conf = 0.8 if m["kind"] == "tld_swap" else (0.9 if m["kind"] == "hyphenation" else 1.0)
    return [
        url_evidence(
            "url.typosquat",
            {**m, "host": c.host_ascii[:200].replace(".", "[.]")},
            f"Domain is one typo away from {brand.name_en}'s official site"
            if m.get("distance") == 1
            else f"Domain closely resembles {brand.name_en}'s official site",
            f"النطاق قريب جداً من الموقع الرسمي لـ «{brand.name_ar}»",
            conf,
        )
    ]


# ---------------------------------------------------------------- combosquat
SPEC_COMBO = SignalSpec(
    name="url.combosquat",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=("url.combosquat",),
)


def _label_parts(label: str) -> list[str]:
    return [p for p in label.split("-") if p]


def combosquat_match(c: CanonicalURL, reg: BrandRegistry) -> tuple[Brand, str, str, str | None] | None:
    label = c.domain_label
    if not label:
        return None
    lab_c = compact(label)
    parts = _label_parts(label)
    for b in reg.brands:
        for tok in b.tokens_en:
            if len(tok) >= 5:
                if tok in lab_c and lab_c != tok:
                    rem = lab_c.replace(tok, "", 1)
                    if rem:
                        return b, tok, rem, _has_combo(rem)
            elif len(tok) >= 3 and tok in parts and len(parts) > 1:
                rem = "".join(p for p in parts if p != tok)
                w = _has_combo(rem)
                if w:
                    return b, tok, rem, w
        for tok in b.tokens_ar:
            if tok in lab_c and lab_c != tok:
                rem = lab_c.replace(tok, "", 1)
                if rem:
                    return b, tok, rem, _has_combo(rem)
    return None


@signal(SPEC_COMBO)
def run_combo(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    reg = registry(ctx)
    if not c.ok or c.is_ip or reg.is_official(c.registrable):
        return []
    m = combosquat_match(c, reg)
    if not m:
        return []
    b, tok, rem, word = m
    obs: dict[str, object] = {
        "brand_id": b.brand_id,
        "token": tok,
        "extra": rem[:100],
        "combo_word": word,
        "host": c.host_ascii[:200].replace(".", "[.]"),
    }
    return [
        url_evidence(
            "url.combosquat",
            obs,
            f"Domain bolts '{word or rem}' onto the name of {b.name_en}",
            f"النطاق يضيف كلمة «{word or rem}» إلى اسم «{b.name_ar}»",
            0.9 if word else 0.5,
        )
    ]


# ------------------------------------------------- brand in subdomain or path
SPEC_BSP = SignalSpec(
    name="url.brand_in_subdomain_or_path",
    family="url",
    tier="T1",
    input_types=("url", "message", "email"),
    timeout_ms=T1_TIMEOUT_MS,
    network="none",
    emits=("url.brand_in_subdomain_or_path",),
)


def _find_token(text: str, whole_labels: list[str], reg: BrandRegistry) -> tuple[Brand, str] | None:
    t = compact(text)
    for b in reg.brands:
        for tok in b.tokens_en:
            if (len(tok) >= 5 and tok in t) or (len(tok) >= 3 and tok in whole_labels):
                return b, tok
        for tok in b.tokens_ar:
            if tok in t:
                return b, tok
    return None


@signal(SPEC_BSP)
def run_bsp(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    reg = registry(ctx)
    if not c.ok or c.is_ip or reg.is_official(c.registrable):
        return []
    out: list[Evidence] = []
    host_s = c.host
    # (a) a verified official domain written inside the host: adpolice.gov.ae.evil.test
    for b in reg.brands:
        for d in b.verified_domains:
            if c.subdomain and ("." + d + ".") in ("." + host_s + ".") and not host_s.endswith("." + d):
                out.append(
                    url_evidence(
                        "url.brand_in_subdomain_or_path",
                        {
                            "where": "subdomain",
                            "brand_id": b.brand_id,
                            "official_domain_in_host": True,
                            "host": c.host_ascii[:200].replace(".", "[.]"),
                        },
                        f"The address starts with {b.name_en}'s real domain but belongs to another site",
                        f"العنوان يبدأ بنطاق «{b.name_ar}» الحقيقي لكنه يتبع موقعاً آخر",
                        1.0,
                    )
                )
                return out
    sub_labels = c.subdomain_labels + ([c.domain_label] if c.is_private_suffix else [])
    hit = _find_token(".".join(sub_labels), [compact(x) for x in sub_labels], reg) if sub_labels else None
    if hit:
        b, tok = hit
        out.append(
            url_evidence(
                "url.brand_in_subdomain_or_path",
                {
                    "where": "subdomain",
                    "brand_id": b.brand_id,
                    "token": tok,
                    "official_domain_in_host": False,
                    "host": c.host_ascii[:200].replace(".", "[.]"),
                },
                f"{b.name_en} appears in the address, but the site is not {b.name_en}'s",
                f"اسم «{b.name_ar}» ظاهر في العنوان لكن الموقع ليس تابعاً له",
                0.9,
            )
        )
    elif c.path_decoded or c.query_decoded:
        text = c.path_decoded + " " + c.query_decoded
        hit = _find_token(text, [], reg)
        if hit:
            b, tok = hit
            out.append(
                url_evidence(
                    "url.brand_in_subdomain_or_path",
                    {
                        "where": "path",
                        "brand_id": b.brand_id,
                        "token": tok,
                        "official_domain_in_host": False,
                        "host": c.host_ascii[:200].replace(".", "[.]"),
                    },
                    f"{b.name_en} is named in the page path, but the site is not {b.name_en}'s",
                    f"اسم «{b.name_ar}» ورد في مسار الصفحة لكن الموقع ليس تابعاً له",
                    0.5,
                )
            )
    return out
