"""rep.gsb (Google Safe Browsing v4 Lookup) and rep.urlhaus (URLhaus host lookup).

Both are implemented but stay disabled unless their key is in the environment
(``GOOGLE_SAFE_BROWSING_API_KEY`` / ``URLHAUS_AUTH_KEY``, see DECISIONS: no keys yet). Disabled means
``fl_feed_enabled{feed}=0`` and a ``feed_disabled`` evidence error, with no network call.

Both APIs are POST-only, while ``GuardedHTTPClient.fetch`` allows GET/HEAD only. The adapters therefore call
``ctx.http.post(url, json=..., data=..., headers=..., timeout=...)`` when the guarded client offers it, and report
``post_unsupported`` otherwise. Proposal to builder-security: add a POST method restricted to an allow-list of
JSON API hosts (safebrowsing.googleapis.com, urlhaus-api.abuse.ch). The signal never builds its own client.
"""

from __future__ import annotations

import json
import os
from typing import Any

from falcon_core.security.http import FetchFailed
from falcon_core.security.ssrf import SSRFBlocked
from falcon_core.signals.base import Evidence, SignalContext, SignalSpec, async_signal
from falcon_core.signals.cache import get_cache
from falcon_core.signals.domain.common import error_evidence
from falcon_core.signals.reputation import metrics
from falcon_core.signals.url.canonical import canonicalize

GSB_SPEC = SignalSpec(
    name="rep.gsb",
    family="reputation",
    tier="T1",
    input_types=("url",),
    timeout_ms=2000,
    network="egress_proxy",
    emits=("rep.gsb",),
    cache_ttl_s=300,
)
URLHAUS_SPEC = SignalSpec(
    name="rep.urlhaus",
    family="reputation",
    tier="T1",
    input_types=("url",),
    timeout_ms=2000,
    network="egress_proxy",
    emits=("rep.urlhaus",),
    cache_ttl_s=300,
)
GSB_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
URLHAUS_HOST_URL = "https://urlhaus-api.abuse.ch/v1/host/"
GSB_THREATS = (
    "MALWARE",
    "SOCIAL_ENGINEERING",
    "UNWANTED_SOFTWARE",
    "POTENTIALLY_HARMFUL_APPLICATION",
)
HTTP_BUDGET_S = 1.8


def gsb_key() -> str | None:
    return os.environ.get("GOOGLE_SAFE_BROWSING_API_KEY") or None


def urlhaus_key() -> str | None:
    return os.environ.get("URLHAUS_AUTH_KEY") or None


def gsb_request_body(url: str) -> dict[str, Any]:
    return {
        "client": {"clientId": "falcon-lens", "clientVersion": "0.1"},
        "threatInfo": {
            "threatTypes": list(GSB_THREATS),
            "platformTypes": ["ANY_PLATFORM"],
            "threatEntryTypes": ["URL"],
            "threatEntries": [{"url": url}],
        },
    }


async def _post_json(ctx: SignalContext, url: str, **kw: Any) -> Any:
    post = getattr(ctx.http, "post", None)
    if post is None:
        raise _Fail("post_unsupported")
    try:
        res = await post(url, timeout=HTTP_BUDGET_S, **kw)
    except SSRFBlocked as exc:
        raise _Fail(f"ssrf_blocked:{exc.reason.value}") from exc
    except FetchFailed as exc:
        raise _Fail(exc.reason.value) from exc
    if res.status == 429:
        raise _Fail("rate_limited")
    if res.status >= 400:
        raise _Fail(f"http_{res.status}")
    try:
        return json.loads(res.body)
    except ValueError as exc:
        raise _Fail("bad_json") from exc


class _Fail(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _hit(spec: SignalSpec, feed: str, observed: dict[str, Any], en: str, ar: str) -> Evidence:
    return Evidence(
        signal=spec.name,
        family="reputation",
        observed=observed,
        display={"en": en, "ar": ar},
        polarity="risk",
        source=feed,
        tier=spec.tier,
    )


def _miss(spec: SignalSpec, feed: str) -> Evidence:
    return Evidence(
        signal=spec.name,
        family="reputation",
        observed={"hit": False, "feed": feed},
        display={"en": f"No match in {feed}", "ar": f"لا توجد مطابقة في {feed}"},
        polarity="neutral",
        source=feed,
        tier=spec.tier,
    )


@async_signal(GSB_SPEC)
async def run_gsb(ctx: SignalContext) -> list[Evidence]:
    key = gsb_key()
    metrics.set_enabled("gsb", key is not None)
    if key is None:
        return [error_evidence(GSB_SPEC, "feed_disabled", "gsb")]
    if not ctx.url:
        return []
    c = canonicalize(ctx.url)
    cache = get_cache(ctx)
    ck = f"gsb:{c.host_ascii}{c.path}"  # cache key only; never logged
    cached = await cache.get(ck)
    if isinstance(cached, dict):
        matches = cached.get("matches", [])
    else:
        try:
            doc = await _post_json(ctx, f"{GSB_URL}?key={key}", json=gsb_request_body(c.url))
        except _Fail as exc:
            return [error_evidence(GSB_SPEC, f"gsb_{exc.code}", "gsb")]
        matches = doc.get("matches", []) if isinstance(doc, dict) else []
        await cache.set(ck, {"matches": matches}, 300)
    if not matches:
        return [_miss(GSB_SPEC, "gsb")]
    types = sorted({str(m.get("threatType", ""))[:40] for m in matches if isinstance(m, dict)})
    return [
        _hit(
            GSB_SPEC,
            "gsb",
            {"hit": True, "feed": "gsb", "threat_types": types},
            "Flagged by Google Safe Browsing",
            "مُصنّف خطرًا لدى Google Safe Browsing",
        )
    ]


@async_signal(URLHAUS_SPEC)
async def run_urlhaus(ctx: SignalContext) -> list[Evidence]:
    key = urlhaus_key()
    metrics.set_enabled("urlhaus", key is not None)
    if key is None:
        return [error_evidence(URLHAUS_SPEC, "feed_disabled", "urlhaus")]
    if not ctx.url:
        return []
    c = canonicalize(ctx.url)
    if not c.ok or not c.host_ascii:
        return []
    cache = get_cache(ctx)
    ck = f"urlhaus:{c.host_ascii}"
    cached = await cache.get(ck)
    if isinstance(cached, dict):
        doc = cached
    else:
        try:
            doc = await _post_json(ctx, URLHAUS_HOST_URL, data={"host": c.host_ascii}, headers={"Auth-Key": key})
        except _Fail as exc:
            return [error_evidence(URLHAUS_SPEC, f"urlhaus_{exc.code}", "urlhaus")]
        if not isinstance(doc, dict):
            return [error_evidence(URLHAUS_SPEC, "urlhaus_bad_json", "urlhaus")]
        await cache.set(ck, doc, 300)
    status = doc.get("query_status")
    if status == "no_results":
        return [_miss(URLHAUS_SPEC, "urlhaus")]
    if status != "ok":
        return [error_evidence(URLHAUS_SPEC, f"urlhaus_{str(status)[:40]}", "urlhaus")]
    urls = [u for u in doc.get("urls", []) if isinstance(u, dict)]
    online = sum(1 for u in urls if u.get("url_status") == "online")
    return [
        _hit(
            URLHAUS_SPEC,
            "urlhaus",
            {
                "hit": True,
                "feed": "urlhaus",
                "url_count": int(doc.get("url_count") or len(urls)),
                "online": online,
            },
            "Host is listed in URLhaus (malware distribution)",
            "النطاق مدرج في URLhaus (توزيع برمجيات خبيثة)",
        )
    ]
