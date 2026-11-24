"""infra.hosting / infra.rdap: recorded DoH + RDAP answers, no network. IANA example.com address as the public IP (documentation ranges are refused by the guard)."""

import asyncio
import json
from typing import Any

from netfakes import Ctx, FakeHTTP, fixture, result, validate

from falcon_core.security.http import FetchFailed, FetchFailReason
from falcon_core.security.ssrf import BlockReason, SSRFBlocked
from falcon_core.signals import REGISTRY
from falcon_core.signals.domain import infra

DOH = "https://dns.google/resolve"
BOOT = "https://data.iana.org/rdap/dns.json"
RDAP = "https://rdap.registry.test/com/v1/domain/"


def doh(*data: str, rtype: int = 1) -> Any:
    return result({"Status": 0, "Answer": [{"name": "x.", "type": rtype, "TTL": 60, "data": d} for d in data]})


def hosting_routes(a: Any = None, aaaa: Any = None) -> dict[str, Any]:
    return {
        f"{DOH}?name=falcon-demo-shop.com&type=AAAA": aaaa or result({"Status": 0}),  # before A: prefix routing
        f"{DOH}?name=falcon-demo-shop.com&type=A": a or doh("93.184.216.34"),
        f"{DOH}?name=34.216.184.93.origin.asn.cymru.com&type=TXT": doh(
            '"64500 | 93.184.216.0/24 | AE | ripencc | 2020-01-01"', rtype=16
        ),
        f"{DOH}?name=AS64500.asn.cymru.com&type=TXT": doh(
            '"64500 | AE | ripencc | 2010-01-01 | EXAMPLE-NET, AE"', rtype=16
        ),
    }


async def run(name: str, ctx: Any) -> list[Any]:
    _spec, fn = REGISTRY[name]
    return await fn(ctx)


def test_registered_enrichment_and_budget() -> None:
    for n in ("infra.hosting", "infra.rdap"):
        spec, _ = REGISTRY[n]
        assert spec.criticality == "enrichment" and spec.timeout_ms <= 2000 and spec.network == "egress_proxy"


async def test_hosting_ip_and_asn() -> None:
    http = FakeHTTP(hosting_routes())
    evs = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/login?x=1", http=http))
    validate(evs)
    ip, asn = evs
    assert ip.signal == "infra.ip" and ip.observed["resolved_ips"] == ["93.184.216.34"]
    assert asn.signal == "infra.hosting_asn"
    assert (asn.observed["asn"], asn.observed["as_name"], asn.observed["country"]) == (64500, "EXAMPLE-NET, AE", "AE")
    assert asn.observed["retrieved_at"].endswith("Z") and "Team Cymru" in asn.observed["hosting_source"]
    assert ip.weight == 0 and asn.weight == 0 and ip.polarity == "neutral"
    assert all(c.startswith("https://dns.google/") for c in http.calls)


async def test_hosting_cached() -> None:
    http = FakeHTTP(hosting_routes())
    ctx = Ctx(url="https://falcon-demo-shop.com/", http=http)
    await run("infra.hosting", ctx)
    n = len(http.calls)
    await run("infra.hosting", ctx)
    assert len(http.calls) == n


async def test_private_and_metadata_ips_are_dropped() -> None:
    routes = hosting_routes(a=doh("10.0.0.5", "169.254.169.254", "127.0.0.1"))
    (ev,) = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(routes)))
    assert ev.error == "hosting_no_public_ip" and ev.observed is None


async def test_mixed_answers_keep_only_public() -> None:
    routes = hosting_routes(a=doh("192.168.1.1", "93.184.216.34"))
    ip, _asn = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(routes)))
    assert ip.observed["resolved_ips"] == ["93.184.216.34"] and ip.observed["non_public_dropped"] == 1


async def test_private_ip_literal_host_makes_no_network_call() -> None:
    http = FakeHTTP({})
    (ev,) = await run("infra.hosting", Ctx(url="http://10.1.2.3/login", http=http))
    assert ev.error == "hosting_no_public_ip" and http.calls == []


async def test_ssrf_block_and_timeout_become_gap_not_exception() -> None:
    blocked = FakeHTTP({DOH: SSRFBlocked(BlockReason.PRIVATE)})
    (ev,) = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/", http=blocked))
    assert ev.error and ev.error.startswith("hosting_") and ev.observed is None
    slow = FakeHTTP({DOH: ("sleep", 5)})
    (ev2,) = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/", http=slow))
    assert ev2.error
    assert FetchFailed(FetchFailReason.TIMEOUT)  # sanity for the fake


async def test_asn_failure_keeps_ip_and_flags_gap() -> None:
    routes = hosting_routes()
    routes[f"{DOH}?name=34.216.184.93.origin.asn.cymru.com&type=TXT"] = result({"Status": 3})
    evs = await run("infra.hosting", Ctx(url="https://falcon-demo-shop.com/", http=FakeHTTP(routes)))
    assert evs[0].signal == "infra.ip" and evs[0].error is None
    assert evs[1].error == "asn_lookup_failed"


async def test_ipv6_cymru_name() -> None:
    n = infra.cymru_origin_name("2001:db8::1")
    assert n.endswith(".origin6.asn.cymru.com") and n.startswith("1.0.0.0.")
    assert infra.cymru_origin_name("93.184.216.34") == "34.216.184.93.origin.asn.cymru.com"


async def test_no_host_no_evidence() -> None:
    assert await run("infra.hosting", Ctx(url="data:text/html,hi", http=FakeHTTP({}))) == []


# ------------------------------------------------------------------ RDAP


def full_rdap() -> dict[str, Any]:
    doc = json.loads(fixture("rdap_domain.json"))
    doc["events"].append({"eventAction": "last changed", "eventDate": "2026-11-18T00:00:00Z"})
    doc["status"] = ["client transfer prohibited"]
    doc["nameservers"] = [{"ldhName": "NS2.EXAMPLE-DNS.TEST"}, {"ldhName": "ns1.example-dns.test"}]
    doc["entities"] = [
        {
            "roles": ["registrant"],
            "vcardArray": [
                "vcard",
                [
                    ["fn", {}, "text", "Jane Q Registrant"],
                    ["email", {}, "text", "jane@private.example"],
                    ["tel", {}, "uri", "tel:+971500000000"],
                    ["adr", {}, "text", ["", "", "1 Secret St", "", "", "", ""]],
                ],
            ],
        },
        {
            "roles": ["technical"],
            "vcardArray": ["vcard", [["fn", {}, "text", "Tech Person"], ["email", {}, "text", "tech@private.example"]]],
        },
        {
            "roles": ["registrar"],
            "publicIds": [{"type": "IANA Registrar ID", "identifier": "9999"}],
            "vcardArray": ["vcard", [["fn", {}, "text", "Synthetic Registrar LLC"]]],
            "entities": [
                {
                    "roles": ["abuse"],
                    "vcardArray": [
                        "vcard",
                        [["email", {}, "text", "abuse@registrar.test"], ["tel", {}, "uri", "tel:+1.5550100"]],
                    ],
                }
            ],
        },
    ]
    return doc


async def test_rdap_registrar_full_fields() -> None:
    http = FakeHTTP({BOOT: result(fixture("iana_dns.json")), RDAP: result(full_rdap())})
    (ev,) = await run("infra.rdap", Ctx(url="https://secure.falcon-demo-shop.com/", http=http))
    validate([ev])
    o = ev.observed
    assert ev.signal == "infra.rdap_registrar" and ev.weight == 0 and ev.polarity == "neutral"
    assert o["registrar"] == "Synthetic Registrar LLC" and o["registrar_iana_id"] == "9999"
    assert (o["created"], o["expires"], o["updated"]) == (
        "2026-11-15T10:20:30+00:00",
        "2027-11-15T10:20:30+00:00",
        "2026-11-16T00:00:00+00:00",
    )
    assert o["nameservers"] == ["ns1.example-dns.test", "ns2.example-dns.test"]
    assert o["status"] == ["client transfer prohibited"]
    assert o["abuse_email"] == "abuse@registrar.test" and o["abuse_phone"] == "+1.5550100"
    assert o["retrieved_at"].endswith("Z") and o["rdap_source"].startswith("https://rdap.registry.test/")


async def test_rdap_drops_personal_registrant_fields() -> None:
    http = FakeHTTP({BOOT: result(fixture("iana_dns.json")), RDAP: result(full_rdap())})
    (ev,) = await run("infra.rdap", Ctx(url="https://falcon-demo-shop.com/", http=http))
    blob = json.dumps(ev.to_dict())
    for secret in ("Jane", "private.example", "+971500000000", "Secret St", "Tech Person"):
        assert secret not in blob


async def test_rdap_failure_is_gap() -> None:
    http = FakeHTTP({BOOT: result(fixture("iana_dns.json")), RDAP: FetchFailed(FetchFailReason.TIMEOUT)})
    (ev,) = await run("infra.rdap", Ctx(url="https://falcon-demo-shop.com/", http=http))
    assert ev.error and ev.error.startswith("rdap_") and ev.observed is None


def test_event_loop_sanity() -> None:
    assert asyncio.iscoroutinefunction(infra.hosting_lookup)
