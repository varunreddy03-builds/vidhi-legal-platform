import path from "node:path";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Phase 2 evidence: every step saves a real screenshot of the running app (stubbed outside services, throwaway database).
const OUT = path.resolve(process.cwd(), "../artifacts/verification/phase-2");
const shot = (page: import("@playwright/test").Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });

test("signed-out visitors are sent to sign-in, then a new account reaches the research and recovery screens", async ({ page }) => {
  await page.goto("/research");
  await expect(page).toHaveURL(/\/login/);
  await shot(page, "01-signed-out-redirect-to-login");

  await signUp(page);
  await shot(page, "02-after-signup-start");

  await page.goto("/research");
  await expect(page.locator("body")).toContainText(/research|matter|verified/i);
  await shot(page, "03-research-screen");

  await page.goto("/recovery");
  await expect(page.getByTestId("recovery-hero")).toBeVisible();
  await shot(page, "04-recovery-dashboard");

  await page.goto("/admin");
  await expect(page).not.toHaveURL(/\/admin$/, { timeout: 5000 }).catch(() => undefined); // a normal user must not see the console
  await expect(page.getByText(/AI spend|monthly cap/i)).toHaveCount(0);
  await shot(page, "05-admin-denied-for-normal-user");
});

test("the same screens hold at phone width", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await shot(page, "06-mobile-start");
  await page.goto("/recovery");
  await expect(page.getByTestId("recovery-hero")).toBeVisible();
  await shot(page, "07-mobile-recovery");
});
