import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

async function skipTour(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("guided-tour")).toHaveCount(0); // the tour no longer opens by itself
}

test("going offline shows a notice and coming back removes it; the page title says where you are", async ({ page, context }) => {
  await signUp(page);
  await skipTour(page);
  await expect(page).toHaveTitle(/VIDHI/);
  await expect(page.getByTestId("offline-banner")).toHaveCount(0);
  await context.setOffline(true);
  await expect(page.getByTestId("offline-banner")).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByTestId("offline-banner")).toHaveCount(0);
});

test("the version number is shown under More on a phone", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await skipTour(page);
  await page.getByTestId("mobile-nav-more").click();
  await expect(page.getByTestId("app-version")).toContainText(/VIDHI version \d+\.\d+\.\d+/);
});
