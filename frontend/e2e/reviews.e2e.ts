import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// Review requests between colleagues. A one-person firm can ask itself (as with draft approval), which lets one account walk through the whole flow.
// The rules (who may decide, one decision, other organisations) are tested in backend/tests/test_reviews.py.

test("a review is requested for a document and decided, and the tab fits a phone", async ({ page }) => {
  await signUp(page);
  const m = await page.request.post("/api/matters", { data: { title: `Review ${unique()}`, description: "", parties: "", jurisdiction_id: "IN" } });
  expect(m.ok()).toBeTruthy();
  const matter = (await m.json()) as { id: string };
  const up = await page.request.post(`/api/matters/${matter.id}/documents`, { multipart: { file: { name: `memo-${unique()}.txt`, mimeType: "text/plain", buffer: Buffer.from(`A short memo ${unique()}\n`) } } });
  expect(up.ok()).toBeTruthy();

  await page.goto(`/matters/${matter.id}`);
  await page.getByTestId("tab-reviews").click();
  await expect(page.getByTestId("review-empty")).toBeVisible();
  await page.getByTestId("review-item").selectOption({ index: 1 });
  await page.getByTestId("review-reviewer").selectOption({ index: 1 });
  await page.getByTestId("review-note").fill("Please check the dates");
  await scan(page, "Reviews tab");
  await page.getByTestId("review-send").click();
  await expect(page.getByTestId("review-item-row")).toHaveCount(1);
  await expect(page.getByTestId("review-item-row")).toContainText("Waiting");

  await page.getByTestId("review-comment").fill("Looks right");
  await page.getByTestId("review-approve").click();
  await expect(page.getByTestId("review-item-row")).toContainText("Approved");
  await expect(page.getByTestId("review-item-row")).toContainText("Looks right");
  await expect(page.getByTestId("review-approve")).toHaveCount(0);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
