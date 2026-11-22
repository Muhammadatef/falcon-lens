from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakeredis
import jsonschema
import pytest
from referencing import Registry, Resource

from falcon_api.fake_worker import build_doc, handle
from falcon_api.jobs import last_key
from falcon_core.contracts.verdict import Verdict
from tests.conftest import FakeStore

VID = "vd_" + "A" * 26
CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def validate_contract(doc: dict[str, Any]) -> None:
    resources = [(f.name, Resource.from_contents(json.loads(f.read_text()))) for f in CONTRACTS.glob("*.schema.json")]
    registry: Registry = Registry().with_resources(resources)  # type: ignore[assignment]
    schema = json.loads((CONTRACTS / "verdict.schema.json").read_text())
    jsonschema.Draft202012Validator(schema, registry=registry).validate(doc)


@pytest.mark.parametrize(
    ("url", "feed", "expected"),
    [
        ("http://fixtures/phish/", False, "dangerous"),
        ("http://fixtures/official/", False, "no_warning_signs"),
        ("http://listed.test/x", True, "dangerous"),
        ("http://169.254.169.254/", False, "suspicious"),
    ],
)
def test_fake_docs_validate_against_contract(url: str, feed: bool, expected: str) -> None:
    for final in (False, True):
        doc = build_doc(VID, "url", url, "fixture", final=final, in_feed=feed)
        Verdict.model_validate(doc)
        validate_contract(doc)
        assert doc["final"] is final
    assert build_doc(VID, "url", url, "live", final=True, in_feed=feed)["verdict"] == expected


async def test_handle_publishes_partial_then_final() -> None:
    r: Any = fakeredis.FakeAsyncRedis(decode_responses=True)
    await handle(
        r,
        {"verdict_id": VID, "input_type": "url", "payload_json": '{"url": "http://f/phish"}'},
        None,
    )
    assert json.loads(await r.get(last_key(VID)))["final"] is True
    assert FakeStore().docs == {}


async def test_feed_membership_uses_hashes_only() -> None:
    from falcon_api.canon import canonicalize_url, sha256_hex

    r: Any = fakeredis.FakeAsyncRedis(decode_responses=True)
    url = "http://listed.test/x"
    job = {"verdict_id": VID, "input_type": "url", "payload_json": json.dumps({"url": url})}
    await r.sadd("feed:openphish", url)  # plaintext must NOT match
    await handle(r, job, None)
    assert json.loads(await r.get(last_key(VID)))["verdict"] == "suspicious"
    await r.sadd("feed:openphish", sha256_hex(canonicalize_url(url)))
    await handle(r, job, None)
    assert json.loads(await r.get(last_key(VID)))["verdict"] == "dangerous"
