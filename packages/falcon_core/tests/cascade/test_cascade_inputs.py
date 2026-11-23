"""Message / email / image pipelines through the cascade (H5) with stubbed sandbox and no network."""

from __future__ import annotations

from typing import Any

from cascade_helpers import assert_valid, make_cascade, rules

from falcon_core.cascade import CallbackSink, StubSandboxClient, new_verdict_id
from falcon_core.cascade.ai import AgentExtractorAdapter, Extracted
from falcon_core.cascade.testing import DEMO_BENIGN_URL, DEMO_LOOKALIKE_URL, benign_features, phish_features


async def check(kind: str, data: bytes, **kw: Any) -> CallbackSink:
    cascade, _ = make_cascade(**kw)
    sink = CallbackSink()
    await cascade.run_input(new_verdict_id(), kind, data, sink)  # type: ignore[arg-type]
    return sink


async def test_message_with_dangerous_link_fires_h5() -> None:
    text = f"Your account is locked, verify now: {DEMO_LOOKALIKE_URL}".encode()
    sink = await check("message", text, sandbox=StubSandboxClient(default=phish_features()))
    final = sink.docs[-1]
    assert_valid(final)
    assert final["input_type"] == "message" and final["final"]
    assert final["verdict"] == "dangerous" and "H5" in rules(final)
    assert [d["tier_reached"] for d in sink.docs] == ["T1", "T2"]
    links = [e for e in final["evidence"] if e["signal"] == "message.link_verdict"]
    assert links and links[0]["observed"]["verdict"] == "dangerous"
    assert "." not in links[0]["observed"]["url"].replace("[.]", "").split("/")[2]  # defanged


async def test_plain_message_has_no_link_verdict_and_is_not_degraded() -> None:
    sink = await check(
        "message", b"See you at the garden club on Saturday.", sandbox=StubSandboxClient(default=benign_features())
    )
    final = sink.docs[-1]
    assert_valid(final)
    assert not final["degraded"] and "H5" not in rules(final)
    assert not any(e["signal"] == "message.link_verdict" for e in final["evidence"])


async def test_message_with_benign_link_is_not_h5() -> None:
    text = f"Garden club events: {DEMO_BENIGN_URL}".encode()
    final = (await check("message", text, sandbox=StubSandboxClient(default=benign_features()))).docs[-1]
    assert_valid(final)
    assert "H5" not in rules(final)
    assert any(e["signal"] == "message.link_verdict" for e in final["evidence"])


async def test_child_failure_degrades_the_message() -> None:
    text = f"verify: {DEMO_LOOKALIKE_URL}".encode()
    final = (await check("message", text, sandbox=StubSandboxClient(error="timeout"))).docs[-1]
    assert_valid(final)
    # the child URL itself is degraded/suspicious, never "no warning signs" for a failed check
    assert final["verdict"] != "no_warning_signs"


EML = (
    b"From: Falcon Demo Bank <alerts@falcon-demo-bank-login.test>\r\n"
    b"To: user@example.test\r\nSubject: Verify your account\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"Sign in now: https://falcon-demo-bank-login.test/secure/\r\n"
)


async def test_email_goes_through_the_same_pipeline() -> None:
    sink = await check("email", EML, sandbox=StubSandboxClient(default=phish_features()))
    final = sink.docs[-1]
    assert_valid(final)
    assert final["input_type"] == "email" and final["verdict"] == "dangerous" and "H5" in rules(final)
    assert any(e["signal"] == "email.link_verdict" for e in final["evidence"])


async def test_invalid_image_is_degraded_never_no_warning() -> None:
    final = (await check("image", b"not an image at all")).docs[-1]
    assert_valid(final)
    assert final["input_type"] == "image" and final["degraded"]
    assert final["verdict"] != "no_warning_signs"


async def test_extractor_adapter_is_used_for_message_text() -> None:
    calls: list[str] = []

    class Ex(AgentExtractorAdapter):
        def __init__(self) -> None:
            pass

        async def extract_text(self, kind: str, text: str, verdict_id: str, registrable_domain: str | None = None):  # type: ignore[no-untyped-def]
            calls.append(kind)
            out = Extracted()
            out.route = "local"
            return out

    sink = await check("message", b"hello there", extractor=Ex())
    assert calls == ["message"]
    assert sink.docs[-1]["model_route"] == "local"
    assert_valid(sink.docs[-1])


async def test_child_link_verdict_evidence_carries_display_url_not_userinfo_or_pii() -> None:
    host = DEMO_LOOKALIKE_URL.split("://")[1]
    text = f"Verify: https://secret.user:pw0rd@{host}?email=test.user@example.invalid".encode()
    final = (await check("message", text, sandbox=StubSandboxClient(default=phish_features()))).docs[-1]
    links = [e for e in final["evidence"] if e["signal"] == "message.link_verdict"]
    assert links
    blob = str(final)
    for leak in ("secret.user", "pw0rd", "test.user", "example.invalid"):
        assert leak not in blob


# ---- image / QR (fixtures: services/api/tests/fixtures/qr, TEST FIXTURE, Falcon Demo Bank .test only) ----
import io  # noqa: E402
from pathlib import Path  # noqa: E402

QR_DIR = Path(__file__).resolve().parents[3].parent / "services/api/tests/fixtures/qr"


def _qr_png(text: str) -> bytes:
    import zxingcpp
    from PIL import Image

    bc = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.QRCode, text, width=400, height=400)
    buf = io.BytesIO()
    Image.fromarray(bc).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def _sandbox_for(official: bool) -> StubSandboxClient:
    return StubSandboxClient(default=benign_features() if official else phish_features())


async def test_official_qr_matches_pasted_link_and_is_not_degraded() -> None:
    data = (QR_DIR / "02-qr-official.png").read_bytes()
    img = (await check("image", data, sandbox=_sandbox_for(True))).docs[-1]
    link = (await check("message", b"http://falcon-demo-bank.test/", sandbox=_sandbox_for(True))).docs[-1]
    assert_valid(img)
    assert img["verdict"] == link["verdict"] == "no_warning_signs"
    assert not img["degraded"]
    skipped = [e for e in img["evidence"] if e["signal"] == "image.ocr_skipped"]
    assert skipped and skipped[0]["weight"] == 0


async def test_phishing_qr_is_dangerous() -> None:
    # The demo-kit poster uses an http .test host the stub harness cannot render; encode the harness lookalike.
    data = _qr_png(DEMO_LOOKALIKE_URL)
    final = (await check("image", data, sandbox=StubSandboxClient(default=phish_features()))).docs[-1]
    assert_valid(final)
    assert final["verdict"] == "dangerous" and "H5" in rules(final)


async def test_image_without_decodable_qr_stays_degraded() -> None:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, "PNG")
    final = (await check("image", buf.getvalue(), sandbox=StubSandboxClient(default=benign_features()))).docs[-1]
    assert_valid(final)
    assert final["degraded"] and final["verdict"] != "no_warning_signs"


async def test_qr_with_two_links_worst_wins() -> None:
    data = _qr_png("http://falcon-demo-bank.test/ http://falcon-demo-bank-login.test/secure/")
    sb = StubSandboxClient(
        default=benign_features(), by_url={"http://falcon-demo-bank-login.test/secure/": phish_features()}
    )
    final = (await check("image", data, sandbox=sb)).docs[-1]
    assert_valid(final)
    assert final["verdict"] == "dangerous"
