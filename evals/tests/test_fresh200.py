from evals.fresh200 import build, metrics


def _r(label, verdict, group="phishing", degraded=False, tier="T1", reasons=(), signals=()):
    return {
        "label": label,
        "verdict": verdict,
        "group": group,
        "degraded": degraded,
        "tier": tier,
        "degraded_reasons": list(reasons),
        "signals": list(signals),
        "latency_s": 2.0,
        "risk_score": 50,
    }


def test_wilson_bounds():
    lo, hi = metrics.wilson(0, 10)
    assert lo == 0.0 and 0.2 < hi < 0.35
    assert metrics.wilson(0, 0) == (0.0, 0.0)


def test_overall_counts_and_f1():
    rows = [_r(1, "dangerous")] * 3 + [_r(1, "no_warning_signs")]
    rows += [_r(0, "suspicious", "legit_global")] + [_r(0, "no_warning_signs", "legit_global")] * 3
    o = metrics.overall(rows, False)
    assert o["counts"] == {"tp": 3, "fn": 1, "fp": 1, "tn": 3}
    assert o["recall"]["value"] == 0.75 and o["precision"]["value"] == 0.75
    assert o["f1"]["value"] == 0.75 and o["accuracy"]["value"] == 0.75
    d = metrics.overall(rows, True)  # the suspicious legit page is not a dangerous-only false positive
    assert d["counts"]["fp"] == 0


def test_dead_pages_reported_separately():
    live = _r(1, "dangerous")
    dead = _r(1, "suspicious", degraded=True, reasons=["dns_failure"])
    assert metrics.is_live(live) and not metrics.is_live(dead)
    s = metrics.summarise([live, dead, _r(0, "no_warning_signs", "legit_uae")])
    assert s["groups"]["phishing_dead_in_sandbox"]["n"] == 1
    assert s["groups"]["phishing_live_in_sandbox"]["n"] == 1
    assert s["groups"]["legit_uae"]["n"] == 1
    assert s["overall_live_phishing_only"]["any_warning"]["counts"]["tp"] == 1


def test_defang_never_leaves_live_url():
    assert metrics.defang("https://a.b.example.org/x?y=1") == "hxxps://a[.]b[.]example[.]org/x?y=1"
    assert metrics.defang("http://evil.example.org/p", host_only=True) == "hxxp://evil[.]example[.]org/…"


def test_canon_and_registered_domain_dedupe():
    assert build.canon_url("hxxps://www.Example[.]com/a/") == build.canon_url("https://example.com/a")
    assert build.reg("hxxp://x.y.example[.]co[.]uk/") == "example.co.uk"
