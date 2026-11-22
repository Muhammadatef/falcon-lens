"""Playwright XSS check for the verdict UI (docs/THREAT_MODEL.md, E: stored XSS on the board).

Every red-team string (case payloads plus classic XSS probes) is placed into a recorded verdict
(reasons, evidence display text, defanged URL) that the browser receives through a mocked API route,
so no backend and no network are involved. The check fails when any of these happens:
  * a payload ran (it sets ``window.__flxss``) or opened a dialog;
  * the page reported a CSP violation (``securitypolicyviolation`` event);
  * an element carrying an inline event handler or a ``javascript:`` URL appeared in the DOM.

Modes
  ``--self-test``  two in-memory renderers (textContent vs innerHTML) under a strict CSP: the safe
                   one must pass and the unsafe one must be caught. Proves the checker itself works.
  default          needs ``FL_WEB_URL`` (e.g. http://localhost:3000) and optionally ``FL_XSS_PATH``
                   (default ``/v/{verdict_id}``). Without FL_WEB_URL it exits 2 "not yet implemented":
                   the web app (feat/web-app) is not merged yet. That is NOT a pass.

Run: ``make xss`` (uses ``uv run --with playwright==1.65.2``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

CASES = Path(__file__).with_name("cases.yaml")
VERDICT_ID = "vd_redteamxss0001"

PROBES = [
    "<script>window.__flxss=1</script>",
    "<img src=x onerror=\"window.__flxss=1\">",
    "<svg onload=\"window.__flxss=1\"></svg>",
    "\"><img src=x onerror=window.__flxss=1>",
    "'><script>window.__flxss=1</script>",
    "<a href=\"javascript:window.__flxss=1\">tap</a>",
    "<iframe srcdoc=\"<script>parent.__flxss=1</script>\"></iframe>",
    "<details open ontoggle=\"window.__flxss=1\">",
    "{{constructor.constructor('window.__flxss=1')()}}",
    "<style>@import 'hxxp://attacker-demo[.]example/x.css';</style>",
    "‮<img src=x onerror=window.__flxss=1>",
    "<math><mtext></mtext><mglyph><svg><mtext><style><img src=x onerror=window.__flxss=1>",
]

INIT = """
window.__flxss = 0; window.__cspv = [];
document.addEventListener('securitypolicyviolation', e => window.__cspv.push(e.violatedDirective + ' ' + e.blockedURI));
"""

DOM_CHECK = """() => {
  const bad = [];
  for (const el of document.querySelectorAll('*')) {
    for (const a of el.attributes) {
      if (/^on/i.test(a.name)) bad.push(el.tagName + '[' + a.name + ']');
      if (/^\\s*javascript:/i.test(a.value)) bad.push(el.tagName + '[' + a.name + '=javascript:]');
    }
    if (el.tagName === 'SCRIPT' && /^\\s*(window|parent)\\.__flxss/.test(el.textContent || '')) bad.push('SCRIPT(payload)');
    if (el.tagName === 'IFRAME' && el.getAttribute('srcdoc')) bad.push('IFRAME[srcdoc]');
  }
  return bad;
}"""


def payloads() -> list[str]:
    raw = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    out = list(PROBES)
    for c in raw["cases"]:
        for key in ("inject",):
            if isinstance(c.get(key), str):
                out.append(c[key][:200])
        if isinstance(c.get("attack"), str):
            out.append(c["attack"][:200])
        out.extend(u[:200] for u in c.get("units") or [])
    return list(dict.fromkeys(out))


def verdict_with(strings: list[str]) -> dict[str, Any]:
    """A recorded verdict (contracts/verdict.schema.json shape) carrying attacker strings."""
    evidence = [
        {
            "id": f"ev_xss{i:012d}",
            "signal": "page.cred_form",
            "family": "page",
            "observed": {"note": s},
            "display": {"en": s[:200], "ar": s[:200]},
            "weight": 1.5,
            "polarity": "risk",
            "hard_rule": None,
            "source": "sandbox",
            "tier": "T2",
            "confidence": 1.0,
            "error": None,
        }
        for i, s in enumerate(strings)
    ]
    reasons = [
        {"ar": s[:220], "en": s[:220], "evidence_ids": [evidence[i]["id"]], "generated_by": "template"}
        for i, s in enumerate(strings[:3])
    ]
    return {
        "schema_version": "1.0",
        "verdict_id": VERDICT_ID,
        "input_type": "url",
        "canonical_url": "hxxps://falcon-demo-bank-login[.]example/" + strings[0][:80],
        "verdict": "dangerous",
        "risk_score": 97,
        "calibrated_probability": 0.97,
        "evidence": evidence,
        "reasons": reasons,
        "actions": {"en": ["Do not enter any details."], "ar": ["لا تُدخل أي بيانات."]},
        "tier_reached": "T2",
        "model_route": "none",
        "degraded": False,
        "final": True,
        "latency_ms": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "source": "replay",
    }


SAFE_PAGE = """<!doctype html><html><head><meta http-equiv="Content-Security-Policy"
content="default-src 'none'; script-src 'nonce-t'; style-src 'none'; img-src 'none'; frame-src 'none'"></head>
<body><main id=m></main><script nonce=t>
const v = %s; const m = document.getElementById('m');
for (const r of v.reasons) { const p = document.createElement('p'); p.textContent = r.en + ' / ' + r.ar; m.append(p); }
for (const e of v.evidence) { const li = document.createElement('li'); li.textContent = e.display.en; m.append(li); }
const u = document.createElement('code'); u.textContent = v.canonical_url; m.append(u);
</script></body></html>"""
UNSAFE_PAGE = SAFE_PAGE.replace("p.textContent = r.en", "p.innerHTML = r.en").replace(
    "script-src 'nonce-t'", "script-src 'nonce-t' 'unsafe-inline'"
)


def _assess(page: Any, dialogs: list[str]) -> dict[str, Any]:
    page.wait_for_timeout(300)
    return {
        "executed": bool(page.evaluate("window.__flxss")),
        "dialogs": dialogs,
        "csp_violations": page.evaluate("window.__cspv"),
        "dangerous_dom": page.evaluate(DOM_CHECK),
    }


def _failed(r: dict[str, Any]) -> bool:
    return bool(r["executed"] or r["dialogs"] or r["csp_violations"] or r["dangerous_dom"])


def _server(html: str) -> Any:
    # Playwright passes (route, request) to handlers with two parameters, so no default-arg closures.
    def serve(route: Any) -> None:
        if route.request.url.rstrip("/") == "http://xss-selftest.test":
            route.fulfill(status=200, content_type="text/html", body=html)
        else:
            route.abort()  # nothing leaves the browser

    return serve


def _json(body: str) -> Any:
    def fulfil(route: Any) -> None:
        route.fulfill(status=200, content_type="application/json", body=body)

    return fulfil


def run_self_test() -> int:
    from playwright.sync_api import sync_playwright

    strings = payloads()
    # Embedded in a <script>: escape "</" so a payload cannot close the tag of the test page itself.
    v = json.dumps(verdict_with(strings)).replace("</", "<\\/")
    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, html in (("safe", SAFE_PAGE % v), ("unsafe", UNSAFE_PAGE % v)):
            ctx = browser.new_context()
            page = ctx.new_page()
            dialogs: list[str] = []
            page.on("dialog", lambda d, dl=dialogs: (dl.append(d.message), d.dismiss()))
            page.add_init_script(INIT)

            page.route("**/*", _server(html))
            page.goto("http://xss-selftest.test/", wait_until="domcontentloaded")
            results[name] = _assess(page, dialogs)
            ctx.close()
        browser.close()
    print(json.dumps(results, indent=2)[:2000])
    ok = not _failed(results["safe"]) and _failed(results["unsafe"])
    print(f"xss self-test: {'ok' if ok else 'FAILED'} ({len(strings)} strings)")
    return 0 if ok else 1


def run_ui(base: str, path_tpl: str) -> int:
    from playwright.sync_api import sync_playwright

    strings = payloads()
    failures: list[dict[str, Any]] = []
    chunk = 3  # three strings per verdict (the UI shows at most three reasons)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i in range(0, len(strings), chunk):
            body = json.dumps(verdict_with(strings[i : i + chunk]))
            ctx = browser.new_context()
            page = ctx.new_page()
            dialogs: list[str] = []
            page.on("dialog", lambda d, dl=dialogs: (dl.append(d.message), d.dismiss()))
            page.add_init_script(INIT)

            page.route("**/v1/verdicts/**", _json(body))
            page.route("**/v1/check/**", _json(body))
            page.goto(base.rstrip("/") + path_tpl.format(verdict_id=VERDICT_ID), wait_until="domcontentloaded")
            r = _assess(page, dialogs)
            if _failed(r):
                failures.append({"strings": strings[i : i + chunk], **r})
            ctx.close()
        browser.close()
    out = Path(__file__).resolve().parents[1] / "results"
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out / f"xss-{ts}.json").write_text(
        json.dumps({"base": base, "strings": len(strings), "failures": failures}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"xss: {len(failures)} failing verdict renders out of {-(-len(strings) // chunk)}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.redteam.xss_check")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return run_self_test()
    base = os.environ.get("FL_WEB_URL")
    if not base:
        print(
            "make xss: not yet implemented against the real UI: the web app (feat/web-app) is not merged. "
            "Set FL_WEB_URL to a running verdict UI, or run with --self-test. This is NOT a pass.",
            file=sys.stderr,
        )
        return 2
    return run_ui(base, os.environ.get("FL_XSS_PATH", "/v/{verdict_id}"))


if __name__ == "__main__":
    raise SystemExit(main())
