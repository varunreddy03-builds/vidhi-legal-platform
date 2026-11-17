import { expect, test, type Page } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Legal Recovery is NOT part of the app by default (backend RECOVERY_ENABLED). The e2e server runs with the switch ON so the older Recovery tests keep covering the code, so this file answers the public
// /api/auth/options itself with "recovery": false, which is exactly what an installation with the switch off sends. The server half (every /recovery route answers 404, the jobs send nothing)
// is in backend/tests/test_recovery_off.py.

async function recoveryOff(page: Page) {
  await page.route("**/api/auth/options", (route) =>
    route.fulfill({ json: { password: true, google: false, turnstile_site_key: null, signup_mode: "open", recovery: false } }),
  );
}

test("with Legal Recovery off there is no sign of it in the menus, the settings, the help or the addresses", async ({ page }) => {
  await recoveryOff(page);
  await signUp(page);

  for (const path of ["/start", "/settings", "/help", "/dashboard"]) {
    await page.goto(path);
    await expect(page.locator("main, [role=main], body").first()).toBeVisible();
    await expect(page.locator('a[href^="/recovery"]'), `a link to Recovery on ${path}`).toHaveCount(0);
  }

  await page.goto("/settings");
  await expect(page.getByTestId("settings-recovery-link")).toHaveCount(0);
  await expect(page.getByTestId("settings-more")).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText("Legal Recovery");
  await scan(page, "Settings with Legal Recovery off");

  await page.goto("/help");
  await expect(page.locator("body")).not.toContainText("Legal Recovery");
  await expect(page.locator("body")).not.toContainText("demand notice");

  for (const path of ["/recovery", "/recovery/guide", "/recovery/cases/abc", "/consent/sometoken"]) {
    await page.goto(path);
    await expect(page, `${path} should leave the Recovery address`).not.toHaveURL(/\/recovery|\/consent/);
    await expect(page.getByTestId("start-greeting").or(page.getByTestId("home-toolkit"))).toBeVisible(); // it lands on the start page or the home page, never on a Recovery page
  }
});

test("with Legal Recovery off the signed-out home page and the phone's More menu do not mention it", async ({ page }) => {
  await recoveryOff(page);
  await page.goto("/");
  await expect(page.getByTestId("home-toolkit")).toBeVisible();
  await expect(page.getByTestId("home-recovery-note")).toHaveCount(0);

  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.getByTestId("mobile-nav-more").click();
  await expect(page.getByTestId("more-sheet")).toBeVisible();
  await expect(page.getByTestId("more-sheet").getByText("Legal Recovery")).toHaveCount(0);
  await expect(page.getByTestId("more-sheet").locator('a[href^="/recovery"], [data-testid="more-recovery"]')).toHaveCount(0);
  await scan(page, "More menu on a phone with Legal Recovery off");
});

test("with Legal Recovery on (the test server's own answer) it is there", async ({ page }) => {
  await signUp(page);
  await page.goto("/settings");
  await expect(page.getByTestId("settings-recovery-link")).toBeVisible();
  await page.goto("/recovery");
  await expect(page).toHaveURL(/\/recovery/);
});
