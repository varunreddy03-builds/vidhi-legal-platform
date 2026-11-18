import { expect, test } from "@playwright/test";
import { scan } from "./helpers";

// The security page must never claim a certification VIDHI does not have.
test("the security page is public, accessible, and says plainly that SOC 2 and ISO 27001 are not held", async ({ page }) => {
  await page.goto("/security");
  const box = page.getByTestId("security-standards");
  await expect(box).toContainText("not");
  await expect(box).toContainText("SOC 2 Type II");
  await expect(box).toContainText("ISO/IEC 27001");
  await expect(page.getByTestId("security-page")).not.toContainText(/we are (SOC|ISO)|SOC 2 (certified|compliant)|ISO 27001 (certified|compliant)/i);
  await scan(page, "Security page");
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
