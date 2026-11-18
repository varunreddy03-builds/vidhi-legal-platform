import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// The start of the app tells a person everything VIDHI does, from one list (src/lib/everything.ts) that the Start page and the About page share.

test("the Start page lists every part, the About page explains each one and what it cannot do yet", async ({ page }) => {
  await signUp(page);
  await page.goto("/start");
  const all = page.getByTestId("start-everything");
  await expect(all).toContainText("Everything in VIDHI");
  for (const id of ["research", "matters", "vault", "tax", "translate", "directory", "authority", "deadlines", "reviews", "connections"]) await expect(page.getByTestId(`start-part-${id}`)).toBeVisible();
  await page.getByTestId("start-part-vault").click();
  await expect(page).toHaveURL(/\/vault$/);

  await page.goto("/start");
  await page.getByTestId("start-about-link").click();
  await expect(page).toHaveURL(/\/about$/);
  const about = page.getByTestId("about-page");
  await expect(about).toContainText("it does not represent anyone or give legal advice");
  await expect(page.getByTestId("about-promise")).toContainText("Lawyers decide");
  // honest about what is not finished
  await expect(page.getByTestId("about-part-connections")).toContainText("iManage is not built");
  await expect(page.getByTestId("about-part-tax")).toContainText("carries no tax law of its own");
  await expect(page.getByTestId("about-part-rules")).toContainText("does not claim SOC 2 or ISO 27001");
  await expect(about).not.toContainText(/we are (SOC|ISO)|SOC 2 (certified|compliant)|ISO 27001 (certified|compliant)/i);
  await scan(page, "About VIDHI");
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
