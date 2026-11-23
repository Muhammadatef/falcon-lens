import { DEMO_DANGEROUS, DEMO_NWS } from "../../lib/demo";
import { XSS, dangerousStream, degradedVerdict, nwsStream, withId, xssVerdict } from "../fixtures";
import { expect, newVerdictId, registerScenario, scenarioLog, setPrefs, submitText, test, token } from "./helpers";

test.describe("check page: progressive verdict from the API stream", () => {
  test("dangerous stream: tiers reveal, provisional chip, final plate, reasons cite evidence, actions", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: dangerousStream(id) });

    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", "ar");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(page.getByTestId("result")).toHaveCount(0);

    await submitText(page, `https://falcon-demo-bank-secure.test/login?c=${t}`);

    // While streaming: no verdict word yet, a provisional "suspicious" chip appears, evidence arrives by tier.
    await expect(page.getByTestId("pending")).toBeVisible();
    await expect(page.getByTestId("provisional-chip")).toContainText("علامات مريبة");
    await expect(page.getByTestId("verdict-plate")).toHaveCount(0);
    await expect(page.getByTestId("tier-T1").getByTestId("evidence-row")).toHaveCount(3);
    await expect(page.getByTestId("tier-T2")).toHaveAttribute("data-status", "running");

    // Final.
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
    await expect(page.getByTestId("verdict-card")).toHaveAttribute("data-verdict", "dangerous");
    await expect(page.getByTestId("provisional-chip")).toHaveCount(0);
    await expect(page.getByTestId("case-status")).toContainText("اكتمل الفحص");
    await expect(page.getByTestId("impersonated")).toContainText("بنك الصقر التجريبي");
    await expect(page.getByTestId("risk-score")).toHaveText("97 / 100");
    await expect(page.getByTestId("reasons").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("evidence-row")).toHaveCount(7);
    await expect(page.getByTestId("tier-T2")).toHaveAttribute("data-status", "done");
    await expect(page.getByTestId("tier-T3")).toHaveAttribute("data-status", "skipped");
    await expect(page.getByTestId("tier-T3")).toContainText("قاعدة حاسمة حسمت النتيجة");
    await expect(page.getByTestId("trace").locator("li")).toHaveCount(4);

    // Actions and report channels come from the verdict.
    await expect(page.getByTestId("act-now").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("act-acted").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("act-report")).toContainText("999");
    await expect(page.getByTestId("act-report")).toContainText("غير تابع لشرطة أبوظبي");
    await expect(page.getByTestId("caution")).toHaveCount(0);

    // Clicking an evidence id highlights its row in the investigation timeline.
    await page.getByTestId("cite").filter({ hasText: "ev_dom0age001" }).click();
    await expect(page.locator('[data-testid="evidence-row"][data-evidence="ev_dom0age001"]')).toHaveClass(/hit/);
    await expect(page.locator('[data-testid="evidence-row"][data-evidence="ev_dom0age001"]')).toBeInViewport();

    // The URL is defanged text, never a link; the result holds no anchors at all.
    await expect(page.getByTestId("defanged-url")).toHaveText("hxxps://falcon-demo-bank-secure[.]test/login");
    await expect(page.getByTestId("result").locator("a")).toHaveCount(0);
    await expect(page.getByTestId("source-badge")).toHaveCount(0); // live data wears no demo badge

    // Real request went to the real endpoint, and the page is reload-proof.
    const log = await scenarioLog(request, t);
    expect(log.requests).toHaveLength(1);
    expect(log.requests[0]).toMatchObject({ kind: "url" });
    expect(log.requests[0]!.contentType).toContain("application/json");
    await expect(page).toHaveURL(new RegExp(`\\?id=${id}$`));
    await page.reload();
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("verdict-id")).toHaveText(id);
  });

  test("no_warning_signs: exact wording, caution first, never a provisional or 'safe'", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: nwsStream(id) });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);

    await expect(page.getByTestId("tier-T0").getByTestId("evidence-row")).toHaveCount(1);
    // Partial verdicts say no_warning_signs here; the UI must not say so before `final`.
    await expect(page.getByTestId("provisional-chip")).toHaveCount(0);
    await expect(page.getByTestId("verdict-word")).toHaveText("لم نجد علامات تحذير");
    await expect(page.getByTestId("verdict-plate")).toContainText("هذا ليس ضماناً");
    await expect(page.getByTestId("caution").locator("li")).toHaveCount(3);

    // Caution block precedes "what to do now".
    const order = await page.locator(".acts > .act").evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-testid")));
    expect(order.slice(0, 2)).toEqual(["caution", "act-now"]);
    await expect(page.getByTestId("tier-T2")).toHaveAttribute("data-status", "skipped");
    await expect(page.getByTestId("tier-T2")).toContainText("قاعدة حاسمة حسمت النتيجة"); // H3 (verified official domain)

    const text = await page.locator("body").innerText();
    expect(text).not.toMatch(/\bsafe\b/i);
    expect(text).not.toContain("آمن");
    // No tick / check icon: the plate icon is the lens-with-dash.
    await expect(page.getByTestId("verdict-card")).toHaveAttribute("data-verdict", "no_warning_signs");

    await page.getByTestId("lang-toggle").click();
    await expect(page.getByTestId("verdict-word")).toHaveText("No warning signs found");
    expect(await page.locator("body").innerText()).not.toMatch(/\bsafe\b/i);
  });

  test("degraded verdict shows the 'could not complete every check' note", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 200, verdict: degradedVerdict(id) }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);

    await expect(page.getByTestId("verdict-word")).toHaveText("مريب");
    await expect(page.getByTestId("degraded")).toContainText("لم نتمكن من إكمال كل الفحوص");
    await expect(page.locator('[data-testid="evidence-row"][data-evidence="ev_sandbox0err"]')).toContainText("تعذّر هذا الفحص");
    await expect(page.getByTestId("impersonated")).toHaveCount(0);
  });

  test("contract invariants enforced in the client: degraded is never 'no warning signs', and that verdict always has its caution", async ({ page, request }) => {
    // Malformed on purpose: the API should never send either of these.
    const id = newVerdictId();
    const t = token();
    const degradedNws = { ...withId(DEMO_NWS, id), degraded: true, degraded_reasons: ["rdap_unavailable"] };
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 150, verdict: degradedNws }] });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank.test/?c=${t}`);
    await expect(page.getByTestId("result")).toHaveAttribute("data-phase", "final");
    await expect(page.getByTestId("verdict-word")).toHaveText("مريب");
    await expect(page.getByTestId("verdict-card")).toHaveAttribute("data-verdict", "suspicious");
    await expect(page.getByTestId("degraded")).toContainText("لم نتمكن من إكمال كل الفحوص");
    await expect(page.getByTestId("result")).not.toContainText("لم نجد علامات تحذير");

    const id2 = newVerdictId();
    const t2 = token();
    const { caution: _caution, ...actions } = DEMO_NWS.actions;
    void _caution;
    const noCaution = { ...withId(DEMO_NWS, id2), actions } as typeof DEMO_NWS;
    await registerScenario(request, { match: t2, verdictId: id2, steps: [{ delayMs: 150, verdict: noCaution }] });
    await page.getByTestId("new-check").click();
    await submitText(page, `https://falcon-demo-bank.test/?c=${t2}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("لم نجد علامات تحذير");
    await expect(page.getByTestId("caution").locator("li")).toHaveCount(3);
    await expect(page.getByTestId("caution")).toContainText("ليس ضماناً");
    const order = await page.locator(".acts > .act").evaluateAll((nodes) => nodes.map((n) => n.getAttribute("data-testid")));
    expect(order[0]).toBe("caution");
  });

  test("429 rate limit: honest error with Retry-After, no verdict, form usable again", async ({ page, request }) => {
    const t = token();
    await registerScenario(request, { match: t, status: 429, retryAfter: 30 });
    await page.goto("/");
    await submitText(page, `https://x.test/${t}`);

    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "rate_limited");
    await expect(page.getByTestId("problem")).toContainText("طلبات كثيرة");
    await expect(page.getByTestId("retry-after")).toContainText("30");
    await expect(page.getByTestId("verdict-plate")).toHaveCount(0);
    await expect(page.getByTestId("timeline")).toHaveCount(0);
    await expect(page.getByTestId("check-submit")).toBeEnabled();
    await expect(page).not.toHaveURL(/id=/);
  });

  test("API down: says no check was run, never a scripted result", async ({ page }) => {
    await page.goto("/");
    await submitText(page, `https://social.test/someone/status/${token()}`); // no scenario → mock answers 500
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "unavailable");
    await expect(page.getByTestId("problem")).toContainText("لم يُجرَ أي فحص");
    await expect(page.getByTestId("verdict-plate")).toHaveCount(0);
    await expect(page.getByTestId("evidence-row")).toHaveCount(0);
  });

  test("network failure on submit shows the connection error", async ({ page }) => {
    await page.goto("/");
    await page.route("**/v1/check/url", (route) => route.abort("connectionrefused"));
    await submitText(page, "https://x.test/a");
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "network");
  });

  test("stream dropped before final: retry, poll, then 'interrupted' with the partial evidence kept", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    const steps = dangerousStream(id).slice(0, 2);
    await registerScenario(request, { match: t, verdictId: id, steps, drop: true, statusVerdict: steps[1]!.verdict });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);

    await expect(page.getByTestId("interrupted")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByTestId("interrupted")).toContainText("لا تفتح الرابط");
    await expect(page.getByTestId("verdict-plate")).toHaveCount(0);
    await expect(page.getByTestId("evidence-row")).toHaveCount(4);
    const log = await scenarioLog(request, t);
    expect(log.streamOpens).toBe(2); // one reconnect
    expect(log.statusCalls).toBeGreaterThanOrEqual(1); // then the status URL
  });

  test("stream endpoint failing falls back to the status URL and still shows the final verdict", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, streamStatus: 503, statusVerdict: withId(DEMO_DANGEROUS, id) });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر", { timeout: 15_000 });
  });

  test("unknown id in the URL: not found, no verdict", async ({ page }) => {
    await page.goto(`/?id=${newVerdictId()}`);
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "not_found", { timeout: 15_000 });
  });

  test("XSS payloads in every verdict string render as inert text", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 150, verdict: xssVerdict(id) }] });
    await page.goto("/");
    await submitText(page, `https://evil.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await page.getByTestId("tech-toggle").check();
    // Long unbroken attacker strings must not break the layout either.
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);

    // The payloads are on screen as literal text…
    await expect(page.getByTestId("reasons")).toContainText(XSS.script);
    await expect(page.getByTestId("act-now")).toContainText(XSS.img);
    await expect(page.getByTestId("impersonated")).toContainText(XSS.script);
    await expect(page.getByTestId("trace")).toContainText(XSS.img);
    await expect(page.locator('[data-testid="evidence-row"][data-evidence="ev_page0form1"]')).toContainText(XSS.img);
    await expect(page.getByTestId("act-report")).toContainText(XSS.jsUrl);

    // …and none of them became markup, a link, or code.
    const result = page.getByTestId("result");
    await expect(result.locator("img, script, iframe, object, embed, a, [onerror], [onload], [onfocus]")).toHaveCount(0);
    await expect(result.locator("svg:not(.icon):not(.lens-svg)")).toHaveCount(0);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
    expect(await page.evaluate(() => document.querySelectorAll('[href^="javascript:" i]').length)).toBe(0);

    // The URL stays defanged, in an LTR-isolated code element, with bidi controls not reordering it.
    const url = page.getByTestId("defanged-url");
    await expect(url).toHaveAttribute("dir", "ltr");
    await expect(url).toContainText("hxxps://evil[.]test/");
    expect(await url.evaluate((n) => n.tagName)).toBe("CODE");
  });

  test("XSS payload typed into the box is echoed as text and sent as data", async ({ page, request }) => {
    const t = token();
    await registerScenario(request, { match: t, status: 422 });
    await page.goto(`/?text=${encodeURIComponent(`${XSS.img} ${t}`)}`);
    await expect(page.getByTestId("check-input")).toHaveValue(`${XSS.img} ${t}`);
    await page.getByTestId("check-submit").click();
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "invalid");
    await expect(page.getByTestId("result")).toContainText(XSS.img);
    await expect(page.getByTestId("result").locator("img")).toHaveCount(0);
    expect((await scenarioLog(request, t)).requests[0]).toMatchObject({ kind: "message" });
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });
});

test.describe("check page: inputs", () => {
  test("a pasted message goes to the message check; an image goes up as multipart", async ({ page, request }) => {
    const t = token();
    const id = newVerdictId();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict: withId(DEMO_DANGEROUS, id, { input_type: "message", canonical_url: null }) }] });
    await page.goto("/");
    await page.getByTestId("kind-message").click();
    await submitText(page, `عزيزي العميل تم إيقاف بطاقتك ${t} حدّث بياناتك`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("defanged-url")).toHaveCount(0);
    expect((await scenarioLog(request, t)).requests[0]).toMatchObject({ kind: "message" });

    const t2 = token();
    const id2 = newVerdictId();
    await registerScenario(request, { match: t2, verdictId: id2, steps: [{ delayMs: 100, verdict: withId(DEMO_DANGEROUS, id2, { input_type: "image", canonical_url: null }) }] });
    await page.getByTestId("new-check").click();
    await expect(page.getByTestId("result")).toHaveCount(0);
    await page.getByTestId("kind-image").click();
    await page.getByTestId("check-submit").click();
    await expect(page.getByTestId("input-error")).toBeVisible();
    // 1x1 PNG named after the token (TEST FIXTURE image, not a real QR).
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
    await page.getByTestId("check-file").setInputFiles({ name: `qr-${t2}.png`, mimeType: "image/png", buffer: png });
    await expect(page.getByTestId("file-chip")).toContainText(`qr-${t2}.png`);
    await page.getByTestId("check-submit").click();
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    const log = await scenarioLog(request, t2);
    expect(log.requests[0]!.kind).toBe("image");
    expect(log.requests[0]!.contentType).toContain("multipart/form-data");
  });

  test("email: an .eml upload and pasted headers both go up as multipart `file`; headerless text becomes a message", async ({ page, request }) => {
    const t = token();
    const id = newVerdictId();
    await registerScenario(request, { match: t, verdictId: id, steps: [{ delayMs: 100, verdict: withId(DEMO_DANGEROUS, id, { input_type: "email", canonical_url: null }) }] });
    await page.goto("/");
    await page.getByTestId("kind-email").click();
    // TEST FIXTURE email for the invented Falcon Demo Bank.
    await submitText(page, `From: alerts@falcon-demo-bank-secure.test\nSubject: verify ${t}\n\nYour card is blocked.`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    let log = await scenarioLog(request, t);
    expect(log.requests[0]!.kind).toBe("email");
    expect(log.requests[0]!.contentType).toContain("multipart/form-data");

    const t2 = token();
    const id2 = newVerdictId();
    await registerScenario(request, { match: t2, verdictId: id2, steps: [{ delayMs: 100, verdict: withId(DEMO_DANGEROUS, id2, { input_type: "message", canonical_url: null }) }] });
    await page.getByTestId("new-check").click();
    await submitText(page, `Dear customer your card is blocked ${t2}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    log = await scenarioLog(request, t2);
    expect(log.requests[0]!.kind).toBe("message");

    // A file the API rejects (415) gets its own plain sentence.
    await page.getByTestId("new-check").click();
    await page.getByTestId("kind-email").click();
    await page.getByTestId("check-file").setInputFiles({ name: "note.eml", mimeType: "message/rfc822", buffer: Buffer.from("not an email at all") });
    await page.getByTestId("check-submit").click();
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "unsupported");
  });

  test("cache hit: POST answers 200 with the final verdict and no stream is opened; a defanged link is accepted", async ({ page, request }) => {
    const t = token();
    const id = newVerdictId();
    await registerScenario(request, { match: t, verdictId: id, cached: true, steps: [{ delayMs: 0, verdict: withId(DEMO_DANGEROUS, id) }] });
    await page.goto("/");
    await submitText(page, `hxxps://falcon-demo-bank-secure[.]test/login?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page).toHaveURL(new RegExp(`id=${id}`));
    const log = await scenarioLog(request, t);
    expect(log.requests[0]!.kind).toBe("url");
    expect(log.streamOpens).toBe(0);
  });

  test("empty submit is refused locally", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("check-submit").click();
    await expect(page.getByTestId("input-error")).toContainText("الصق رابطاً أو رسالة أولاً");
    await expect(page.getByTestId("result")).toHaveCount(0);
  });
});

test.describe("demo mode is explicit and labelled", () => {
  test("without ?demo=1 there are no demo examples and no ribbon", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("demo-examples")).toHaveCount(0);
    await expect(page.getByTestId("demo-ribbon")).toHaveCount(0);
  });

  test("with ?demo=1 a typed link still goes to the real API; only the labelled buttons replay fixtures", async ({ page, request }) => {
    const t = token();
    await registerScenario(request, { match: t, status: 429, retryAfter: 5 });
    await page.goto("/?demo=1");
    await expect(page.getByTestId("demo-ribbon")).toContainText("DEMO DATA");

    await submitText(page, `https://social.test/someone/status/${t}`);
    await expect(page.getByTestId("problem")).toHaveAttribute("data-problem", "rate_limited");
    await expect(page.getByTestId("verdict-plate")).toHaveCount(0);
    expect((await scenarioLog(request, t)).requests).toHaveLength(1);

    await page.getByTestId("demo-danger").click();
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر", { timeout: 10_000 });
    await expect(page.getByTestId("source-badge")).toContainText("بيانات تجريبية");
    await expect(page.getByTestId("impersonated")).toContainText("بنك الصقر التجريبي");
  });
});

test.describe("language, theme, layout, motion", () => {
  test("English toggle flips direction and persists; theme toggle switches to Sand", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("lang-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.locator("html")).toHaveAttribute("dir", "ltr");
    await expect(page.locator("h1")).toHaveText("Two AI agents between you and the scam.");
    // On a phone the theme switch lives inside the menu.
    if (await page.getByTestId("menu-toggle").isVisible()) {
      await page.getByTestId("menu-toggle").click();
      await page.getByTestId("theme-toggle-menu").click();
    } else {
      await page.getByTestId("theme-toggle").click();
    }
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.getByTestId("check-submit")).toHaveText("Check now");
  });

  test("fits the viewport in both languages with the check button above the fold, and uses the self-hosted fonts", async ({ page, context, baseURL }) => {
    for (const lang of ["ar", "en"] as const) {
      await setPrefs(context, baseURL!, { lang });
      await page.goto("/");
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `horizontal overflow (${lang})`).toBeLessThanOrEqual(0);
      await expect(page.getByTestId("check-submit")).toBeInViewport({ ratio: 1 });
    }
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.fonts.check('17px "Readex Pro Variable"', "افحص Check"))).toBe(true);
    const external = await page.evaluate(() => performance.getEntriesByType("resource").map((r) => r.name).filter((n) => !n.startsWith(location.origin)));
    expect(external, "third-party requests").toEqual([]);
  });

  test("reduced motion still delivers the verdict and evidence", async ({ page, request }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: dangerousStream(id) });
    await page.goto("/");
    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("evidence-row")).toHaveCount(7);
    const sweep = await page.locator(".lens--mini .lens-sweep").evaluate((n) => getComputedStyle(n).display);
    expect(sweep).toBe("none");
  });
});
