import pytest

from falcon_core.signals.url.canonical import canonicalize, free_host_suffix, parse_ipv4


def test_basics_case_port_userinfo():
    c = canonicalize("HTTPS://User:pw@Falcon-Demo-Bank.TEST:443/a/./b/../c?x=1#f")
    assert c.host == "falcon-demo-bank.test"
    assert c.port is None and c.userinfo == "User:pw"
    assert c.path == "/a/c" and c.registrable == "falcon-demo-bank.test"
    assert canonicalize("http://example.test:8080/").port == 8080


def test_userinfo_at_trick_uses_last_at():
    c = canonicalize("https://adpolice.gov.ae@evil.example/login")
    assert c.host == "evil.example" and c.userinfo == "adpolice.gov.ae"


def test_scheme_less_and_backslash():
    assert canonicalize("evil.example/path").host == "evil.example"
    assert canonicalize("evil.example:8080/path").port == 8080
    assert canonicalize("http:\\\\evil.example\\x").host == "evil.example"


@pytest.mark.parametrize(
    "host,quad,obf",
    [
        ("192.168.0.1", "192.168.0.1", False),
        ("3232235521", "192.168.0.1", True),
        ("0xC0A80001", "192.168.0.1", True),
        ("0300.0250.0.1", "192.168.0.1", True),
        ("0xc0.168.1", "192.168.0.1", True),
    ],
)
def test_ip_forms(host, quad, obf):
    assert parse_ipv4(host) == (quad, obf)
    c = canonicalize(f"http://{host}/x")
    assert c.is_ip and c.ip == quad and c.ip_obfuscated is obf


def test_not_ip():
    assert parse_ipv4("1.2.3.4.5") is None and parse_ipv4("example.test") is None
    assert canonicalize("http://[2001:db8::1]:81/").is_ip


def test_idn_punycode_roundtrip_and_arabic():
    c2 = canonicalize("https://شرطة-ابوظبي.test/")
    assert c2.host == "شرطة-ابوظبي.test"
    assert c2.host_ascii.startswith("xn--")
    assert canonicalize("https://" + c2.host_ascii).host == c2.host


def test_fullwidth_dots_and_trailing_dot():
    assert canonicalize("http://example。test./").host == "example.test"


def test_percent_decoding_and_double_encoding():
    c = canonicalize("http://example.test/%61bc/%252e%252e/x?q=%2568ttp")
    assert c.path.startswith("/abc") and c.double_encoded


def test_data_uri():
    c = canonicalize("data:text/html;base64,PGh0bWw+")
    assert c.is_data_uri and c.scheme == "data"


def test_never_raises_on_garbage():
    for s in [
        "",
        " ",
        "http://",
        "://",
        "http://[",
        "http://:::",
        "\x00\x01",
        "http://a:99999999/",
        "a" * 20000,
    ]:
        canonicalize(s)


def test_psl_private_per_subdomain():
    c = canonicalize("https://fl-fixture-0000.github.io/")
    assert (
        c.registrable == "fl-fixture-0000.github.io"
        and c.is_private_suffix
        and c.domain_label == "fl-fixture-0000"
    )
    assert free_host_suffix(c) == "github.io"
    assert free_host_suffix(canonicalize("https://falcon-demo-bank.test/")) is None


def test_gov_ae_suffix():
    c = canonicalize("https://smartservices.adpolice.gov.ae/x")
    assert c.registrable == "adpolice.gov.ae" and c.subdomain == "smartservices"
