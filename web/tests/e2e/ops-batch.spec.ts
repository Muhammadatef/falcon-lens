/** /ops/batch: upload a URL list, watch progress, download the CSV. The server route is mocked; fixtures use .test hosts. */
import { readFile } from "node:fs/promises";
import { expect, test } from "./helpers";

const VERDICTS: Record<string, string> = { "a.test": "dangerous", "b.test": "suspicious", "c.test": "no_warning_signs" };

test("upload a list, see progress, download the strict CSV", async ({ page }) => {
  await page.route("**/api/ops/batch", async (route) => {
    const { url } = route.request().postDataJSON() as { url: string };
    const verdict = VERDICTS[new URL(url).hostname] ?? "dangerous";
    await route.fulfill({ json: { verdict, risk_score: 70, degraded: false, degraded_reasons: [], tier_reached: "T1", top_reasons: ["url.homograph"], latency_ms: 5, verdict_id: `vd_${verdict}`, error: "" } });
  });
  await page.goto("/ops/batch");
  await page.getByTestId("batch-key").fill("operator-key-not-a-secret");
  await page.getByTestId("batch-file").setInputFiles({ name: "urls.txt", mimeType: "text/plain", buffer: Buffer.from("http://a.test/\nhttp://b.test/\nhttp://c.test/\n") });
  await page.getByTestId("batch-start").click();
  await expect(page.getByTestId("batch-download")).toBeVisible();
  await expect(page.getByTestId("batch-progress").locator("progress")).toHaveAttribute("value", "3");
  const download = page.waitForEvent("download");
  await page.getByTestId("batch-download").click();
  const csv = await readFile(await (await download).path(), "utf8");
  const lines = csv.trim().split(/\r?\n/);
  expect(lines).toHaveLength(4);
  expect(lines[1]).toContain("http://a.test/,dangerous,70,fraud");
  expect(lines[2]).toContain("http://b.test/,suspicious,70,fraud");
  expect(lines[3]).toContain("http://c.test/,no_warning_signs,70,legit");
});

test("a wrong operator key shows an error and no download", async ({ page }) => {
  await page.route("**/api/ops/batch", (route) => route.fulfill({ status: 401, json: { error: "unauthorized" } }));
  await page.goto("/ops/batch");
  await page.getByTestId("batch-key").fill("wrong");
  await page.getByTestId("batch-file").setInputFiles({ name: "urls.txt", mimeType: "text/plain", buffer: Buffer.from("http://a.test/\n") });
  await page.getByTestId("batch-start").click();
  await expect(page.getByTestId("batch-error")).toBeVisible();
  await expect(page.getByTestId("batch-download")).toHaveCount(0);
});
