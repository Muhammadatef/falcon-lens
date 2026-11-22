"""url.userinfo_trick, url.bidi_or_zero_width, url.raw_ip_host, url.open_redirect_abuse."""

from __future__ import annotations

from urllib.parse import parse_qsl

from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, signal
from falcon_core.signals.url.canonical import canonicalize
from falcon_core.signals.url.common import T1_TIMEOUT_MS, canon, registry, url_evidence
from falcon_core.signals.url.textutil import BIDI_CHARS, ZERO_WIDTH_CHARS, compact, defang


def _spec(name: str) -> SignalSpec:
    return SignalSpec(
        name=name,
        family="url",
        tier="T1",
        input_types=("url", "message", "email"),
        timeout_ms=T1_TIMEOUT_MS,
        network="none",
        emits=(name,),
    )


SPEC_USERINFO = _spec("url.userinfo_trick")
SPEC_BIDI = _spec("url.bidi_or_zero_width")
SPEC_IP = _spec("url.raw_ip_host")
SPEC_REDIRECT = _spec("url.open_redirect_abuse")


@signal(SPEC_USERINFO)
def run_userinfo(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not c.ok or c.userinfo is None:
        return []
    ui = c.userinfo
    domain_like = "." in ui or "/" in ui or "%2f" in c.raw.lower().split("@")[0]
    reg = registry(ctx)
    ui_c = compact(ui)
    brandish = any(t in ui_c for b in reg.brands for t in b.tokens_en if len(t) >= 5) or any(
        d in ui.lower() for b in reg.brands for d in b.verified_domains
    )
    strong = domain_like or brandish
    return [
        url_evidence(
            "url.userinfo_trick",
            {
                "userinfo_looks_like_domain": domain_like,
                "userinfo_brand": brandish,
                "real_host": defang(c.host_ascii)[:200],
                "userinfo": defang(ui)[:100],
            },
            "The address hides its real host behind an '@' (real site: " + defang(c.host_ascii)[:80] + ")",
            "العنوان يخفي الموقع الحقيقي خلف علامة @ (الموقع الفعلي: " + defang(c.host_ascii)[:80] + ")",
            1.0 if strong else 0.5,
        )
    ]


@signal(SPEC_BIDI)
def run_bidi(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not (c.has_bidi or c.has_zero_width):
        return []
    raw = ctx.url or ctx.text or ""
    from urllib.parse import unquote

    seen = sorted({f"U+{ord(ch):04X}" for ch in unquote(raw) if ch in BIDI_CHARS or ch in ZERO_WIDTH_CHARS})[:8]
    only_joiners = all(s in ("U+200C", "U+200D") for s in seen)
    conf = (
        1.0
        if (c.invisible_in_host or any(s in ("U+202E", "U+202D", "U+2066", "U+2067") for s in seen))
        else (0.5 if only_joiners else 0.8)
    )
    return [
        url_evidence(
            "url.bidi_or_zero_width",
            {"codepoints": seen, "in_host": c.invisible_in_host, "bidi": c.has_bidi, "zero_width": c.has_zero_width},
            "The address contains hidden or text-direction-changing characters",
            "العنوان يحتوي على أحرف مخفية أو تغيّر اتجاه النص",
            conf,
        )
    ]


@signal(SPEC_IP)
def run_ip(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not c.ok or not c.is_ip:
        return []
    return [
        url_evidence(
            "url.raw_ip_host",
            {
                "ip": (c.ip or "")[:64].replace(".", "[.]"),
                "obfuscated_form": c.ip_obfuscated,
                "ipv6": ":" in (c.ip or ""),
            },
            "The link points to a raw IP address instead of a website name"
            + (" (written in a disguised form)" if c.ip_obfuscated else ""),
            "الرابط يشير إلى عنوان IP مباشر بدل اسم موقع" + (" (مكتوب بصيغة مموّهة)" if c.ip_obfuscated else ""),
            1.0,
        )
    ]


REDIRECT_PARAMS = frozenset(
    "url uri redirect redirect_url redirect_uri redirecturl redirecturi return return_url returnurl returnto "
    "return_to next continue dest destination goto go target link to out u r forward redir rurl back "
    "backurl back_url service callback_url successurl success_url checkout_url image_url".split()
)
REDIRECTOR_PATHS = (
    "/redirect",
    "/redir",
    "/out",
    "/away",
    "/goto",
    "/go/",
    "/url",
    "/link",
    "/click",
    "/r/",
    "/l.php",
    "/jump",
)


@signal(SPEC_REDIRECT)
def run_open_redirect(ctx: SignalContext) -> list[Evidence]:
    c = canon(ctx)
    if not c.ok or c.is_ip or c.is_data_uri:
        return []
    reg = registry(ctx)
    found: list[Evidence] = []
    host_official = reg.is_official(c.registrable)
    redirector_path = any(c.path_decoded.lower().startswith(p) for p in REDIRECTOR_PATHS)

    def target_ok(val: str) -> str | None:
        v = val.strip()
        low = v.lower()
        if not (low.startswith(("http://", "https://", "//", "/\\")) or low.startswith("hxxp")):
            return None
        t = canonicalize(v)
        if not t.ok or t.registrable == c.registrable or reg.is_official(t.registrable):
            return None
        return t.host_ascii

    for k, v in parse_qsl(c.query, keep_blank_values=False)[:20]:
        host = target_ok(v)
        if host is None:
            # nested one level (base64-free): value decoded again
            continue
        strong = k.lower() in REDIRECT_PARAMS
        found.append(
            url_evidence(
                "url.open_redirect_abuse",
                {
                    "param": k[:40],
                    "target_host": defang(host)[:200],
                    "host_is_official": host_official,
                    "redirector_path": redirector_path,
                    "host": defang(c.host_ascii)[:200],
                },
                "This link forwards visitors to a different website (" + defang(host)[:80] + ")",
                "هذا الرابط يحوّل الزائر إلى موقع آخر (" + defang(host)[:80] + ")",
                0.9 if strong or redirector_path else 0.5,
            )
        )
        if len(found) >= 2:
            break
    if not found:
        for marker in ("/http://", "/https://", "/http%3a", "/https%3a"):
            i = c.path.lower().find(marker)
            if i != -1:
                host = target_ok(c.path_decoded[i + 1 :])
                if host:
                    found.append(
                        url_evidence(
                            "url.open_redirect_abuse",
                            {
                                "param": "(path)",
                                "target_host": defang(host)[:200],
                                "host_is_official": host_official,
                                "redirector_path": True,
                                "host": defang(c.host_ascii)[:200],
                            },
                            "This link carries another website's address inside its path",
                            "هذا الرابط يحمل عنوان موقع آخر داخل مساره",
                            0.7,
                        )
                    )
                break
    return found
