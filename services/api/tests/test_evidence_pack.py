from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from falcon_api import evidence_pack
from falcon_api.app import build_app
from tests.conftest import OPERATOR_KEY, SANDBOX_KEY, FakeStore, make_doc, make_settings, publish

VID = "vd_01HZZZZZZZZZZZZZZZZZZZZZZZ"


def doc_with_evidence() -> dict[str, Any]:
    d = make_doc(VID, final=True, verdict="dangerous")
    d["canonical_url"] = "hxxps://user:pw@evil[.]example/login?token=SECRET#f"
    d["evidence"] = [
        {
            "id": "ev_aaaaaaaa",
            "signal": "domain.age_days",
            "family": "domain",
            "tier": "T1",
            "source": "rdap",
            "weight": 3.0,
            "polarity": "risk",
            "observed": {
                "age_days": 2,
                "registrar": "Example Registrar",
                "registered_at": "2026-11-20T00:00:00+00:00",
                "domain": "evil.example",
            },
        },
    ]
    d["reasons"] = [{"ar": "نطاق جديد", "en": "New domain", "evidence_ids": ["ev_aaaaaaaa"]}]
    return d


def test_pack_files_hashes_and_defang() -> None:
    raw = evidence_pack.build_pack(doc_with_evidence(), screenshot=b"\x89PNGfake", git_sha="abc123")
    z = zipfile.ZipFile(io.BytesIO(raw))
    assert set(z.namelist()) == {"evidence.json", "takedown.txt", "stix.json", "manifest.json", "screenshot.png"}
    manifest = json.loads(z.read("manifest.json"))
    assert manifest["git_sha"] == "abc123"
    for f in manifest["files"]:
        assert hashlib.sha256(z.read(f["name"])).hexdigest() == f["sha256"]
    ev = json.loads(z.read("evidence.json"))
    assert ev["subject"]["url_defanged"] == "hxxps://evil[.]example/login"
    blob = z.read("evidence.json").decode() + z.read("takedown.txt").decode()
    assert "SECRET" not in blob and "user:pw" not in blob
    assert ev["registration"]["registrar"] == "Example Registrar"
    assert ev["screenshot"]["sha256"] == hashlib.sha256(b"\x89PNGfake").hexdigest()
    assert "hosting: not captured for this check" in ev["gaps"]
    assert "عدسة الصقر" in z.read("takedown.txt").decode()
    assert json.loads(z.read("stix.json"))["type"] == "bundle"


def test_no_screenshot_and_no_raw_message() -> None:
    d = doc_with_evidence()
    d["input_type"] = "message"
    d["evidence"][0]["observed"] = {"text": "send me your otp 123456"}
    z = zipfile.ZipFile(io.BytesIO(evidence_pack.build_pack(d)))
    assert "screenshot.png" not in z.namelist()
    assert "otp" not in z.read("evidence.json").decode()


@pytest.fixture
async def pack_client(redis: Any, store: FakeStore) -> AsyncIterator[httpx.AsyncClient]:
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store)
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_authz_and_download(pack_client: httpx.AsyncClient, redis: Any) -> None:
    await publish(redis, doc_with_evidence())
    url = f"/v1/verdicts/{VID}/evidence-pack"
    assert (await pack_client.get(url)).status_code == 401
    r = await pack_client.get(url, headers={"X-API-Key": SANDBOX_KEY})
    assert r.status_code == 403
    r = await pack_client.get(url, headers={"X-API-Key": OPERATOR_KEY})
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "evidence.json" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()


async def test_not_final_and_unknown(pack_client: httpx.AsyncClient, redis: Any) -> None:
    h = {"X-API-Key": OPERATOR_KEY}
    await publish(redis, make_doc(VID, final=False))
    assert (await pack_client.get(f"/v1/verdicts/{VID}/evidence-pack", headers=h)).status_code == 409
    other = "vd_01HZZZZZZZZZZZZZZZZZZZZZZY"
    assert (await pack_client.get(f"/v1/verdicts/{other}/evidence-pack", headers=h)).status_code == 404


def full_infra_doc() -> dict[str, Any]:
    d = doc_with_evidence()
    d["evidence"] += [
        {
            "id": "ev_bbbbbbbb",
            "signal": "infra.ip",
            "family": "domain",
            "tier": "T1",
            "source": "dns",
            "weight": 0.0,
            "polarity": "neutral",
            "observed": {
                "host": "evil.example",
                "resolved_ips": ["93.184.216.34"],
                "hosting_source": "dns.google DoH",
                "retrieved_at": "2026-11-24T10:00:00Z",
            },
        },
        {
            "id": "ev_cccccccc",
            "signal": "infra.hosting_asn",
            "family": "domain",
            "tier": "T1",
            "source": "cymru",
            "weight": 0.0,
            "polarity": "neutral",
            "observed": {
                "asn": 64500,
                "as_name": "EXAMPLE-NET, AE",
                "country": "AE",
                "prefix": "93.184.216.0/24",
                "hosting_source": "Team Cymru IP-to-ASN (DNS TXT via DoH)",
                "retrieved_at": "2026-11-24T10:00:01Z",
            },
        },
        {
            "id": "ev_dddddddd",
            "signal": "infra.rdap_registrar",
            "family": "domain",
            "tier": "T1",
            "source": "rdap",
            "weight": 0.0,
            "polarity": "neutral",
            "observed": {
                "registrar": "Example Registrar",
                "registrar_iana_id": "9999",
                "created": "2026-11-20T00:00:00+00:00",
                "expires": "2027-11-20T00:00:00+00:00",
                "updated": "2026-11-21T00:00:00+00:00",
                "nameservers": ["ns1[.]example-dns[.]test"],
                "status": ["client transfer prohibited"],
                "abuse_email": "abuse@registrar.test",
                "abuse_phone": "+1.5550100",
                "rdap_source": "https://rdap.registry.test/com/v1/domain/evil.example",
                "retrieved_at": "2026-11-24T10:00:02Z",
            },
        },
        {
            "id": "ev_ffffffff",
            "signal": "domain.cert_issuer",
            "family": "domain",
            "tier": "T1",
            "source": "crt",
            "weight": 0.0,
            "polarity": "neutral",
            "observed": {
                "issuer": "Synthetic CA",
                "not_before": "2026-11-20T00:00:00+00:00",
                "not_after": "2027-02-18T00:00:00+00:00",
            },
        },
        {
            "id": "ev_eeeeeeee",
            "signal": "page.screenshot",
            "family": "page",
            "tier": "T2",
            "source": "sandbox",
            "weight": 0.0,
            "polarity": "neutral",
            "observed": {"sha256": SHOT_SHA, "stored": True},
        },
    ]
    return d


SHOT = b"\x89PNG-test-screenshot"
SHOT_SHA = hashlib.sha256(SHOT).hexdigest()


def test_pack_fills_hosting_whois_and_screenshot_and_drops_gaps() -> None:
    z = zipfile.ZipFile(io.BytesIO(evidence_pack.build_pack(full_infra_doc(), screenshot=SHOT, git_sha="x")))
    ev = json.loads(z.read("evidence.json"))
    h, w = ev["hosting"], ev["whois"]
    assert h["resolved_ips"] == ["93.184.216.34"] and (h["asn"], h["as_name"], h["country"]) == (
        64500,
        "EXAMPLE-NET, AE",
        "AE",
    )
    assert h["country_label"]["en"] == "registry country (RIR)" and "RIR" in h["country_label"]["ar"]
    assert "Team Cymru" in h["source"] and h["retrieved_at"] == "2026-11-24T10:00:01Z"
    assert w["registrar_abuse_email"] == "abuse@registrar.test" and w["nameservers"] == ["ns1[.]example-dns[.]test"]
    assert w["updated"] and w["status"] == ["client transfer prohibited"] and w["retrieved_at"]
    assert ev["screenshot"]["included"] and ev["screenshot"]["captured_at_utc"]
    assert ev["tls"]["issuer"] == "Synthetic CA" and ev["tls"]["not_after"].startswith("2027-02-18")
    assert ev["gaps"] == []
    assert "abuse@registrar.test" in z.read("takedown.txt").decode()
    assert z.read("screenshot.png") == SHOT


def test_personal_registrant_fields_never_reach_the_pack() -> None:
    d = full_infra_doc()
    d["evidence"][2]["observed"]["registrant_email"] = "jane@private.example"  # even if a signal leaked it
    z = zipfile.ZipFile(io.BytesIO(evidence_pack.build_pack(d, screenshot=SHOT)))
    ev = json.loads(z.read("evidence.json"))
    assert "jane@private.example" not in json.dumps(ev) and "registrant_email" not in json.dumps(ev)


def test_gaps_listed_when_infra_missing() -> None:
    ev = json.loads(zipfile.ZipFile(io.BytesIO(evidence_pack.build_pack(doc_with_evidence()))).read("evidence.json"))
    assert "hosting: not captured for this check" in ev["gaps"]
    assert "screenshot: not captured for this check" in ev["gaps"]
    assert ev["whois"]["registrar_abuse_email"] is None


async def test_snapshot_fetcher_reads_only_valid_hash_named_files(tmp_path: Any) -> None:
    screens = tmp_path / "screens"
    screens.mkdir()
    (screens / f"{SHOT_SHA}.png").write_bytes(SHOT)
    fetch = evidence_pack.snapshot_fetcher(tmp_path)
    assert await fetch(SHOT_SHA) == SHOT
    assert await fetch("../../etc/passwd") is None and await fetch("0" * 64) is None
    (screens / f"{'a' * 64}.png").write_bytes(b"tampered")  # name does not match content
    assert await fetch("a" * 64) is None


async def test_endpoint_includes_screenshot_via_state_fetch(redis: Any, store: FakeStore, tmp_path: Any) -> None:
    (tmp_path / "screens").mkdir()
    (tmp_path / "screens" / f"{SHOT_SHA}.png").write_bytes(SHOT)
    app = build_app(make_settings(fl_rate_limit_per_ip_per_min=100), redis=redis, store=store)
    app.state.screenshot_fetch = evidence_pack.snapshot_fetcher(tmp_path)
    await publish(redis, full_infra_doc())
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(f"/v1/verdicts/{VID}/evidence-pack", headers={"X-API-Key": OPERATOR_KEY})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.read("screenshot.png") == SHOT


_SCHEMA = json.loads(
    (__import__("pathlib").Path(__file__).parents[3] / "contracts" / "evidence_pack.schema.json").read_text()
)
_EXEMPT = evidence_pack._EXEMPT_KEYS


def _strings(obj: Any, key: str = "") -> Any:
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key)


def hostile_doc() -> dict[str, Any]:
    d = full_infra_doc()
    d["canonical_url"] = "https://user:pw@Evil.Example:8443/a/b?token=SECRET#frag"
    d["evidence"][0]["observed"].update(
        {
            "final_url": "evil.example/landing?token=SECRET2",
            "redirect_chain": ["http://a.example/x?q=SECRET3", "b.example/y#SECRET4", "u:p@c.example/z"],
            "post_targets": ["collect.example/post?k=SECRET5"],
            "title": "Login at www.evil.example/login?sid=SECRET6 now",
            "nameserver_hint": "ns.evil.example",
        }
    )
    d["evidence"][1]["observed"]["host"] = "login.evil.example"
    d["reasons"][0]["en"] = "Domain evil.example?x=SECRET7 is new"
    return d


def test_every_host_and_url_in_the_pack_is_defanged_and_stripped() -> None:
    raw = evidence_pack.build_pack(hostile_doc(), screenshot=SHOT, git_sha="x")
    z = zipfile.ZipFile(io.BytesIO(raw))
    ev = json.loads(z.read("evidence.json"))
    blob = json.dumps(ev) + z.read("takedown.txt").decode()
    for secret in ("SECRET", "user:pw", "u:p@"):
        assert secret not in blob
    host_re = re.compile(r"(?i)(?<![\w@.-])(?:[a-z0-9-]+\.)+[a-z]{2,}\b")
    for key, text in _strings(ev):
        if key in _EXEMPT:
            continue
        assert evidence_pack.scrub_text(text) == text, (key, text)  # nothing raw is left to defang
        assert not host_re.search(text), (key, text)
        if "[.]" in text or "hxxp" in text:
            assert not re.search(r"[?#@]", text), (key, text)
    assert ev["hosting"]["host"] == "login[.]evil[.]example"
    assert ev["subject"]["url_defanged"] == "hxxps://evil[.]example:8443/a/b"


def test_pack_validates_against_contract_schema() -> None:
    import jsonschema

    for d, shot in ((hostile_doc(), SHOT), (doc_with_evidence(), None)):
        ev = json.loads(zipfile.ZipFile(io.BytesIO(evidence_pack.build_pack(d, screenshot=shot))).read("evidence.json"))
        jsonschema.validate(ev, _SCHEMA)


async def test_snapshot_fetcher_refuses_symlinks_and_trailing_newline(tmp_path: Any) -> None:
    screens = tmp_path / "screens"
    screens.mkdir()
    real = tmp_path / "real.png"
    real.write_bytes(SHOT)
    (screens / f"{SHOT_SHA}.png").symlink_to(real)
    fetch = evidence_pack.snapshot_fetcher(tmp_path)
    assert await fetch(SHOT_SHA) is None
    assert await fetch(SHOT_SHA + "\n") is None
