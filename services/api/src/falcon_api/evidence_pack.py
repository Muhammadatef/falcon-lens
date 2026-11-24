"""Police evidence pack: GET /v1/verdicts/{id}/evidence-pack (operator scope only).

A ZIP with evidence.json, takedown.txt, stix.json, manifest.json and, when captured, screenshot.png.
Privacy: only the defanged host and path of a URL are kept (userinfo, query and fragment are stripped);
no raw message, email or image content is ever included. Facts the pipeline did not capture are
reported as `captured: false` in `gaps`, never invented.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from falcon_core.tools.stix import build_bundle, refang_value

SCHEMA_VERSION = "1.0"
LABELS = {
    "dangerous": ("Dangerous", "خطير"),
    "suspicious": ("Suspicious", "مشبوه"),
    "no_warning_signs": ("No warning signs found", "لم نجد علامات تحذير"),
}
NOTICE_EN = "Prepared by Falcon Lens, an independent tool. Automated analysis; not an official finding."
NOTICE_AR = "أعدّته أداة عدسة الصقر المستقلة. تحليل آلي وليس نتيجة رسمية."
_URL_RE = re.compile(r"^(?:https?|hxxps?)(?:://|\[://\])", re.I)
_PERSONAL_KEY = re.compile(r"registrant|(^|_)(admin|tech|technical|billing)(_|$)", re.I)
_FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def defang(url: str) -> str:
    return url.replace("http", "hxxp").replace(".", "[.]") if url else url


def safe_url(value: Any) -> str | None:
    """Defanged URL with userinfo, query and fragment removed; None when it is not a URL."""
    if not isinstance(value, str) or not _URL_RE.match(value.strip()):
        return None
    try:
        p = urlsplit(refang_value(value.strip()))
        host = (p.hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    port = f":{p.port}" if p.port else ""
    return defang(f"{p.scheme}://{host}{port}{p.path}")


def _walk(obj: Any, key: str) -> list[Any]:
    out: list[Any] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                out.append(v)
            out.extend(_walk(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk(v, key))
    return out


def _first(evidence: list[dict[str, Any]], *keys: str) -> Any:
    for ev in evidence:
        for k in keys:
            for v in _walk(ev.get("observed"), k):
                if v not in (None, "", [], {}):
                    return v
    return None


def _clean_observed(ev: dict[str, Any], url_input: bool) -> Any:
    """Observed values are kept only for URL checks; URL-like strings are stripped and defanged."""
    if not url_input:
        return None

    def clean(v: Any) -> Any:
        if isinstance(v, str):
            return safe_url(v) or v[:200]
        if isinstance(v, dict):
            # defence in depth: personal registrant/admin/tech contact fields are never exported
            return {k: clean(x) for k, x in v.items() if not _PERSONAL_KEY.search(str(k))}
        if isinstance(v, list):
            return [clean(x) for x in v[:50]]
        return v

    return clean(ev.get("observed"))


def _urls(v: Any) -> list[str]:
    items = v if isinstance(v, list) else [v] if v else []
    out = [safe_url(i if isinstance(i, str) else (i.get("url") if isinstance(i, dict) else None)) for i in items]
    return [u for u in out if u]


def _utc(s: str | None) -> datetime:
    try:
        d = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


_TOKEN = re.compile(
    r"(?i)(?<![\w@.-])(?:(?:https?|hxxps?)://[^\s\"'<>]+|(?:[^\s/@\"'<>]+@)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?(?:[/?#][^\s\"'<>]*)?)"
)
# Values that are not hosts/URLs even though they contain dots, or are the registrar's own published contact.
_EXEMPT_KEYS = frozenset(
    {"file", "sha256", "id", "verdict_id", "abuse_contact", "abuse_email", "abuse_phone",
     "registrar_abuse_email", "registrar_abuse_phone", "generated_at", "created_at", "git_sha"}
)  # fmt: skip


def _scrub_token(m: re.Match[str]) -> str:
    raw = m.group(0)
    try:
        p = urlsplit(raw if "://" in raw else "//" + raw)
        host = (p.hostname or "").lower()
        port = f":{p.port}" if p.port else ""
    except ValueError:
        return "[redacted-url]"
    if not host or re.fullmatch(r"[\d.]+", host):
        return raw  # an IP literal is evidence, not a name
    scheme = f"{p.scheme}://" if "://" in raw else ""
    return defang(f"{scheme}{host}{port}{p.path}")  # userinfo, query and fragment are dropped


def scrub_text(s: str) -> str:
    """Defang every host/URL-like token (with or without scheme) and drop userinfo, query and fragment."""
    return _TOKEN.sub(_scrub_token, s.replace("[.]", ".").replace("hxxp", "http"))


def scrub_tree(v: Any, key: str = "") -> Any:
    if isinstance(v, str):
        return v if key in _EXEMPT_KEYS else scrub_text(v)
    if isinstance(v, dict):
        return {k: scrub_tree(x, str(k)) for k, x in v.items()}
    if isinstance(v, list):
        return [scrub_tree(x, key) for x in v]
    return v


def evidence_has(evs: list[dict[str, Any]], signal: str) -> bool:
    return any(e.get("signal") == signal and not e.get("error") and e.get("observed") for e in evs)


def build_evidence(
    doc: dict[str, Any], *, now: datetime, git_sha: str, screenshot_sha256: str | None
) -> dict[str, Any]:
    url_input = doc.get("input_type") == "url"
    evs: list[dict[str, Any]] = [e for e in doc.get("evidence", []) if isinstance(e, dict)]
    by_id = {e.get("id"): e for e in evs}
    label_en, label_ar = LABELS.get(str(doc.get("verdict")), (str(doc.get("verdict")), str(doc.get("verdict"))))
    created = _utc(doc.get("created_at"))

    def ev_view(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": e.get("id"),
            "code": e.get("signal"),
            "family": e.get("family"),
            "tier": e.get("tier"),
            "source": e.get("source"),
            "polarity": e.get("polarity", "neutral"),
            "weight": e.get("weight"),
            "hard_rule": e.get("hard_rule"),
            "value": _clean_observed(e, url_input),
            "display": e.get("display"),
            "error": e.get("error"),
        }

    reasons = [
        {
            "ar": r.get("ar"),
            "en": r.get("en"),
            "evidence": [ev_view(by_id[i]) for i in r.get("evidence_ids", []) if i in by_id],
        }
        for r in doc.get("reasons", [])
    ]
    elapsed = 0
    trace = []
    for s in doc.get("trace") or []:
        ms = int(s.get("ms") or 0)
        trace.append(
            {
                "step": s.get("step"),
                "kind": s.get("kind"),
                "name": s.get("name"),
                "summary": s.get("summary"),
                "ms": ms,
                "at_utc_derived": _iso(created + timedelta(milliseconds=elapsed)),
            }
        )
        elapsed += ms
    tiers = [
        {"tier": t, "evidence_codes": sorted({str(e.get("signal")) for e in evs if e.get("tier") == t})}
        for t in ("T0", "T1", "T2", "T3")
    ]

    canonical = safe_url(doc.get("canonical_url")) if url_input else None
    chain = _urls(_first(evs, "redirect_chain")) if url_input else []
    finals = _urls(_first(evs, "final_url")) if url_input else []
    final_url = finals[0] if finals else None
    domain = _first(evs, "domain", "registrable_domain") if url_input else None

    def pick(*keys: str) -> Any:
        return _first(evs, *keys) if url_input else None

    def sig(*names: str) -> dict[str, Any]:
        """observed dict of the first evidence with one of these signal names (url checks only)."""
        if not url_input:
            return {}
        for ev in evs:
            if ev.get("signal") in names and isinstance(ev.get("observed"), dict) and not ev.get("error"):
                return dict(ev["observed"])
        return {}

    rd = sig("infra.rdap_registrar")
    age = sig("domain.age_days")
    registration = {
        "registrar": rd.get("registrar") or pick("registrar"),
        "registrar_iana_id": rd.get("registrar_iana_id"),
        "created": rd.get("created") or pick("registered_at", "creation_date"),
        "expires": rd.get("expires") or pick("expires_at", "expiry_date"),
        "updated": rd.get("updated") or age.get("last_changed_at"),
        "nameservers": rd.get("nameservers") or pick("nameservers") or [],
        "status": rd.get("status") or [],
        "abuse_contact": rd.get("abuse_email") or pick("abuse_contact", "abuse_email"),
        "abuse_phone": rd.get("abuse_phone"),
        "source": "rdap" if (rd or pick("registered_at", "registrar")) else None,
        "rdap_url": defang(rd["rdap_source"]) if rd.get("rdap_source") else None,
        "retrieved_at": rd.get("retrieved_at"),
    }
    ci = sig("domain.cert_issuer")
    tls = {
        "issuer": ci.get("issuer") or pick("issuer", "cert_issuer"),
        "not_before": ci.get("not_before") or pick("not_before"),
        "not_after": ci.get("not_after") or pick("not_after"),
        "source": "crt.sh (CT logs)" if (ci or pick("issuer", "cert_issuer", "not_before")) else None,
    }
    ipo, asno = sig("infra.ip"), sig("infra.hosting_asn")
    hosting = {
        "host": ipo.get("host"),
        "resolved_ips": ipo.get("resolved_ips") or pick("resolved_ips", "ips") or [],
        "asn": asno.get("asn") or pick("asn"),
        "as_name": asno.get("as_name") or pick("as_name"),
        "country": asno.get("country") or pick("asn_country"),
        "prefix": asno.get("prefix"),
        "source": asno.get("hosting_source") or ipo.get("hosting_source") or pick("hosting_source"),
        "retrieved_at": asno.get("retrieved_at") or ipo.get("retrieved_at") or pick("retrieved_at"),
    }
    whois = {
        "registrar": registration["registrar"],
        "registrar_iana_id": registration["registrar_iana_id"],
        "created": registration["created"],
        "expires": registration["expires"],
        "updated": registration["updated"],
        "nameservers": registration["nameservers"],
        "status": registration["status"],
        "registrar_abuse_email": registration["abuse_contact"],
        "registrar_abuse_phone": registration["abuse_phone"],
        "source": registration["source"],
        "retrieved_at": registration["retrieved_at"],
        "note": "Registrar-level RDAP data only; registrant, admin and tech contacts are never collected.",
    }
    page = {"title": pick("title"), "form_targets": _urls(pick("post_targets", "form_targets"))}
    gaps = [
        f"{name}: not captured for this check"
        for name, d, keys in (
            ("registration", registration, ("registrar", "created", "expires", "nameservers", "abuse_contact")),
            ("whois", whois, ("registrar", "created", "expires", "nameservers")),
            ("tls", tls, ("issuer", "not_before", "not_after")),
            ("hosting", hosting, ("resolved_ips", "asn", "as_name", "country")),
        )
        if not any(d[k] for k in keys)
    ]
    if screenshot_sha256 is None:
        gaps.append("screenshot: not captured for this check")
    if url_input and not evidence_has(evs, "infra.rdap_registrar") and not any(g.startswith("whois") for g in gaps):
        gaps.append("whois: registrar abuse contact not captured")
    doc_out = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "generator": {"tool": "Falcon Lens", "git_sha": git_sha},
        "notice": {"en": NOTICE_EN, "ar": NOTICE_AR},
        "verdict": {
            "verdict_id": doc.get("verdict_id"),
            "verdict": doc.get("verdict"),
            "label": {"en": label_en, "ar": label_ar},
            "risk_score": doc.get("risk_score"),
            "calibrated_probability": doc.get("calibrated_probability"),
            "input_type": doc.get("input_type"),
            "tier_reached": doc.get("tier_reached"),
            "final": doc.get("final"),
            "degraded": doc.get("degraded"),
            "source": doc.get("source", "live"),
            "created_at": _iso(created),
        },
        "subject": {
            "url_defanged": canonical,
            "final_url_defanged": final_url,
            "redirect_chain_defanged": chain,
            "registrable_domain": defang(str(domain)) if domain else None,
            "page_title": page["title"],
            "form_targets_defanged": page["form_targets"],
        },
        "reasons": reasons,
        "evidence": [ev_view(e) for e in evs],
        "tier_trace": {"tiers": tiers, "steps": trace, "note": "at_utc_derived = verdict created_at + cumulative ms"},
        "registration": registration,
        "tls": tls,
        "hosting": hosting,
        "whois": whois,
        "screenshot": {
            "included": screenshot_sha256 is not None,
            "file": "screenshot.png" if screenshot_sha256 else None,
            "sha256": screenshot_sha256,
            "captured_at_utc": _iso(created) if screenshot_sha256 else None,
            "note": "Captured by the isolated sandbox browser during this check; operator-only.",
        },
        "gaps": gaps,
        "privacy": "URLs are defanged with userinfo, query and fragment removed. No raw message or email text.",
    }
    result: dict[str, Any] = scrub_tree(doc_out)
    return result


def build_takedown(ev: dict[str, Any]) -> str:
    v, s = ev["verdict"], ev["subject"]
    reg, host = ev["registration"], ev["hosting"]

    def row(label: str, value: Any) -> str:
        return f"  {label}: {value if value not in (None, '', []) else 'not captured'}"

    facts = "\n".join(
        [
            row("URL (defanged)", s["url_defanged"]),
            row("Final URL (defanged)", s["final_url_defanged"]),
            row("Domain (defanged)", s["registrable_domain"]),
            row("Registrar", reg["registrar"]),
            row("Registered", reg["created"]),
            row("Registrar abuse contact", reg.get("abuse_contact")),
            row("Nameservers", ", ".join(reg.get("nameservers") or [])),
            row("Resolved IPs", ", ".join(host["resolved_ips"])),
            row(
                "ASN / AS name / country",
                " / ".join(str(x) for x in (host["asn"], host["as_name"], host["country"]) if x),
            ),
            row("Verdict", f"{v['label']['en']} (risk {v['risk_score']}/100)"),
            row("Checked (UTC)", v["created_at"]),
            row("Reference", v["verdict_id"]),
        ]
    )
    reasons_en = "\n".join(f"  - {r['en']}" for r in ev["reasons"]) or "  - see evidence.json"
    reasons_ar = "\n".join(f"  - {r['ar']}" for r in ev["reasons"]) or "  - راجع evidence.json"
    return (
        "To: the hosting provider / registrar abuse contact\n"
        "Subject: Report of a suspected phishing or scam site\n\n"
        "We ask you to review the site below, which our automated analysis assessed as likely abusive.\n\n"
        f"{facts}\n\nReasons:\n{reasons_en}\n\n"
        "Attached: evidence.json, stix.json, manifest.json (SHA-256 of every file).\n"
        f"{NOTICE_EN}\n\n"
        "------------------------------------------------------------\n\n"
        "إلى: جهة الإبلاغ عن إساءة الاستخدام لدى مزوّد الاستضافة / مسجّل النطاق\n"
        "الموضوع: بلاغ عن موقع احتيال أو تصيّد مشتبه به\n\n"
        "نرجو مراجعة الموقع أدناه الذي قدّر تحليلنا الآلي أنه على الأرجح مسيء.\n\n"
        f"{facts}\n\nالأسباب:\n{reasons_ar}\n\n"
        "المرفقات: evidence.json و stix.json و manifest.json (بصمة SHA-256 لكل ملف).\n"
        f"{NOTICE_AR}\n"
    )


def build_stix(ev: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    """Reuses the shared STIX builder for this one indicator (refanged patterns, as /v1/intel/stix)."""
    created = ev["verdict"]["created_at"]
    inds: list[dict[str, Any]] = []
    for kind, val in (("url", ev["subject"]["url_defanged"]), ("domain", ev["subject"]["registrable_domain"])):
        if val:
            inds.append({"kind": kind, "value_defanged": val, "first_seen": created})
    vid = str(doc.get("verdict_id", ""))
    inc = {
        "incident_id": "inc_" + vid.removeprefix("vd_"),
        "created_at": created,
        "updated_at": created,
        "type": "single_check",
        "source": ev["verdict"]["source"],
        "indicators": inds,
    }
    return build_bundle(inc, refang=True)


def _dump(obj: Any) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def build_pack(
    doc: dict[str, Any], *, screenshot: bytes | None = None, now: datetime | None = None, git_sha: str | None = None
) -> bytes:
    now = now or datetime.now(UTC)
    sha = git_sha or os.environ.get("FL_GIT_SHA") or os.environ.get("GIT_SHA") or "unknown"
    shot_hash = hashlib.sha256(screenshot).hexdigest() if screenshot else None
    ev = build_evidence(doc, now=now, git_sha=sha, screenshot_sha256=shot_hash)
    files: dict[str, bytes] = {
        "evidence.json": _dump(ev),
        "takedown.txt": build_takedown(ev).encode(),
        "stix.json": _dump(build_stix(ev, doc)),
    }
    if screenshot:
        files["screenshot.png"] = screenshot
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now),
        "git_sha": sha,
        "verdict_id": doc.get("verdict_id"),
        "files": [
            {"name": n, "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)} for n, b in sorted(files.items())
        ],
    }
    files["manifest.json"] = _dump(manifest)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(files):
            z.writestr(zipfile.ZipInfo(n, _FIXED_ZIP_TIME), files[n])
    return buf.getvalue()


ScreenshotFetch = Callable[[str], Awaitable[bytes | None]]
_SHA_RE = re.compile(r"[0-9a-f]{64}")
MAX_SHOT_BYTES = 8 * 1024 * 1024


def screenshot_sha(doc: dict[str, Any]) -> str | None:
    """sha256 of the sandbox PNG recorded in ``page.screenshot`` evidence (hash only; never a path or URL)."""
    for ev in doc.get("evidence", []):
        if isinstance(ev, dict) and ev.get("signal") == "page.screenshot" and isinstance(ev.get("observed"), dict):
            sha = str(ev["observed"].get("sha256", ""))
            if _SHA_RE.fullmatch(sha):
                return sha
    return None


def snapshot_fetcher(root: str | os.PathLike[str]) -> ScreenshotFetch:
    """Read-only access to the sandbox snapshot volume (mounted `:ro` into the API, internal only).

    Only ``screens/<sha256>.png`` is ever read; the name is validated as a sha256, the content is re-hashed and
    must equal it, and the size is capped. Anything else returns None (the pack then lists the gap)."""
    base = Path(root) / "screens"

    async def fetch(sha: str) -> bytes | None:
        if not _SHA_RE.fullmatch(sha):
            return None
        path = base / f"{sha}.png"
        try:
            if base.is_symlink():
                return None
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)  # a symlinked file is refused
            with os.fdopen(fd, "rb") as fh:
                data = fh.read(MAX_SHOT_BYTES + 1)
        except OSError:
            return None
        if len(data) > MAX_SHOT_BYTES:
            return None
        return data if hashlib.sha256(data).hexdigest() == sha else None

    return fetch
