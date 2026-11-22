import { dangerousStream } from "../fixtures";
import { expect, newVerdictId, registerScenario, scenarioLog, submitText, test, token } from "./helpers";

test.describe("CSP and markup hygiene", () => {
  test("strict nonce CSP on every page, and no inline style or handler attributes in server HTML", async ({ request }) => {
    for (const path of ["/", "/campaigns", "/ops", "/?demo=1", `/?id=${newVerdictId()}`]) {
      const response = await request.get(path);
      expect(response.status(), path).toBe(200);
      const csp = response.headers()["content-security-policy"] ?? "";
      expect(csp, path).toMatch(/script-src 'self' 'nonce-[A-Za-z0-9+/=]+' 'strict-dynamic'(;|$)/);
      expect(csp, path).toMatch(/style-src 'self' 'nonce-[A-Za-z0-9+/=]+'(;|$)/);
      expect(csp).not.toContain("unsafe-inline");
      expect(csp).not.toContain("unsafe-eval");
      expect(csp).toContain("default-src 'self'");
      expect(csp).toContain("connect-src 'self'");
      expect(csp).toContain("object-src 'none'");
      expect(csp).toContain("frame-ancestors 'none'");
      expect(csp).not.toMatch(/https?:\/\//);

      const html = await response.text();
      expect(html, `${path}: inline style attribute`).not.toMatch(/<[^>]+\sstyle=/i);
      expect(html, `${path}: inline event handler`).not.toMatch(/<[^>]+\son[a-z]+=/i);
      const nonce = /'nonce-([^']+)'/.exec(csp)![1]!;
      for (const tag of html.match(/<script\b[^>]*>/g) ?? []) expect(tag, path).toContain(`nonce="${nonce}"`);
      expect(html).not.toMatch(/fonts\.googleapis|fonts\.gstatic|cdn\./);
    }
  });

  test("each response gets a fresh nonce", async ({ request }) => {
    const nonces = await Promise.all([0, 1, 2].map(async () => /'nonce-([^']+)'/.exec((await request.get("/")).headers()["content-security-policy"] ?? "")?.[1]));
    expect(new Set(nonces).size).toBe(3);
  });
});

test.describe("PWA", () => {
  test("manifest is installable and declares a POST multipart share target", async ({ page, request }) => {
    await page.goto("/");
    await expect(page.locator('link[rel="manifest"]')).toHaveAttribute("href", "/manifest.webmanifest");
    const manifest = await (await request.get("/manifest.webmanifest")).json();
    expect(manifest).toMatchObject({ lang: "ar", dir: "rtl", display: "standalone", start_url: "/", theme_color: "#070b14" });
    expect(manifest.share_target).toMatchObject({ action: "/share", method: "POST", enctype: "multipart/form-data", params: { title: "title", text: "text", url: "url" } });
    expect(manifest.share_target.params.files[0].name).toBe("files");
    for (const icon of manifest.icons) expect((await request.get(icon.src)).status(), icon.src).toBe(200);
    expect(manifest.icons.some((i: { sizes: string }) => i.sizes === "512x512")).toBe(true);
    expect(manifest.icons.some((i: { purpose: string }) => i.purpose === "maskable")).toBe(true);
  });

  test("share target: shared link starts a real check and lands on its live result", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: dangerousStream(id) });
    const response = await request.post("/share", {
      multipart: { title: "رسالة", text: `https://falcon-demo-bank-secure.test/login?c=${t}`, url: "" },
      headers: { "x-forwarded-for": "203.0.113.7" },
      maxRedirects: 0,
    });
    expect(response.status()).toBe(303);
    expect(response.headers().location).toBe(`/?id=${id}`);
    const log = await scenarioLog(request, t);
    expect(log.requests[0]).toMatchObject({ kind: "url", forwardedFor: "203.0.113.7" });

    await page.goto(response.headers().location!);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");
    await expect(page.getByTestId("verdict-id")).toHaveText(id);
  });

  test("share target: screenshot goes to the image check; failures come back to the box", async ({ page, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: dangerousStream(id) });
    const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==", "base64");
    const shared = await request.post("/share", { multipart: { files: { name: `shot-${t}.png`, mimeType: "image/png", buffer: png } }, maxRedirects: 0 });
    expect(shared.headers().location).toBe(`/?id=${id}`);
    expect((await scenarioLog(request, t)).requests[0]!.kind).toBe("image");

    const failed = await request.post("/share", { multipart: { text: `https://x.test/${token()}` }, maxRedirects: 0 });
    expect(failed.status()).toBe(303);
    expect(failed.headers().location).toBe("/?share=failed");
    await page.goto("/?share=failed");
    await expect(page.getByTestId("share-failed")).toBeVisible();

    const prefill = await request.get(`/share?text=${encodeURIComponent("hello https://x.test/a")}`, { maxRedirects: 0 });
    expect(prefill.headers().location).toBe(`/?text=${encodeURIComponent("hello https://x.test/a")}`);
  });
});

test.describe("service worker: offline shell only", () => {
  test.use({ serviceWorkers: "allow" });

  test("installs, never caches verdicts or pages, and serves the offline page when the network is gone", async ({ page, context, request }) => {
    const id = newVerdictId();
    const t = token();
    await registerScenario(request, { match: t, verdictId: id, steps: dangerousStream(id) });

    await page.goto("/");
    await page.evaluate(async () => { await navigator.serviceWorker.ready; });
    await page.reload(); // now controlled by the worker
    expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

    await submitText(page, `https://falcon-demo-bank-secure.test/?c=${t}`);
    await expect(page.getByTestId("verdict-word")).toHaveText("خطِر");

    const cached = await page.evaluate(async () => {
      const urls: string[] = [];
      for (const name of await caches.keys()) for (const req of await (await caches.open(name)).keys()) urls.push(new URL(req.url).pathname + new URL(req.url).search);
      return urls;
    });
    expect(cached).toContain("/offline.html");
    expect(cached.filter((u) => u.startsWith("/v1/") || u.includes("id=") || u === "/" || u.startsWith("/share"))).toEqual([]);

    await context.setOffline(true);
    await page.goto("/campaigns");
    await expect(page.locator("h1")).toHaveText("أنت غير متصل بالإنترنت");
    await expect(page.locator("body")).toContainText("A check needs a connection");
    await context.setOffline(false);
  });
});
