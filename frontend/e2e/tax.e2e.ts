import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// The tax workspace: tax matters, and a reply outline filled in by code with no law of its own (the rule is also unit-tested in src/lib/taxOutline.test.ts).

test("a tax matter is created and a notice reply outline is made without any law of its own", async ({ page }) => {
  await signUp(page);
  await page.goto("/tax");
  await expect(page.getByTestId("tax-note")).toContainText("does not carry tax law of its own");
  await expect(page.getByTestId("tax-empty")).toBeVisible();
  await page.getByTestId("tax-authority").fill("The Assessing Officer, Ward 3");
  await page.getByTestId("tax-points").fill("Cash deposits\nLate filing");
  await page.getByTestId("tax-make").click();
  const text = page.getByTestId("tax-result");
  await expect(text).toHaveValue(/NOT FOR FILING/);
  await expect(text).toHaveValue(/3\.2 Point raised: Late filing/);
  await expect(text).toHaveValue(/to be filled by the advocate/);
  await scan(page, "Tax workspace with an outline");

  const name = `Tax ${unique()}`;
  await page.getByTestId("tax-title-input").fill(name);
  await page.getByTestId("tax-create").click();
  await expect(page).toHaveURL(/\/matters\//);
  await page.goto("/tax");
  await expect(page.getByTestId("tax-matter").filter({ hasText: name })).toHaveCount(1);
});

test("the tax workspace fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/tax");
  await expect(page.getByTestId("tax-make")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  await scan(page, "Tax workspace on a phone");
});
