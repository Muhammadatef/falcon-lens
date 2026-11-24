from __future__ import annotations

import hashlib
import io
import json
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
