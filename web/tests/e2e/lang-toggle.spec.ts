import { test, expect } from "@playwright/test";

// The language toggle must switch server-rendered pages at once, without a manual reload.
for (const path of ["/docs", "/results", "/docs/cascade", "/history"]) {
  test(`language toggle re-renders ${path} immediately (EN -> AR -> EN)`, async ({ page, context, baseURL }) => {
    await context.addCookies([{ name: "fl_lang", value: "en", url: baseURL! }]);
    await page.goto(path);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    const h1 = page.locator("main h1").first();
    const en = (await h1.innerText()).trim();
    let loads = 0;
    page.on("load", () => (loads += 1));
    await page.getByTestId("lang-toggle").click();
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(h1).not.toHaveText(en, { timeout: 8_000 });
    await expect(h1).toHaveText(/[؀-ۿ]/);
    await page.getByTestId("lang-toggle").click();
    await expect(h1).toHaveText(en, { timeout: 8_000 });
    expect(loads).toBe(0);
  });
}
