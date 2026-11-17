import { expect, test } from "@playwright/test";
import { newUser, scan, signUp } from "./helpers";

async function skipTour(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("guided-tour")).toHaveCount(0); // the tour no longer opens by itself
}

async function newMatter(page: import("@playwright/test").Page, title: string) {
  await page.goto("/matters");
  await page.getByTestId("new-matter-button").click();
  await page.getByTestId("matter-title-input").fill(title);
  await page.getByTestId("matter-parties-input").fill("Acme Traders v. Beta Stores");
  await page.getByTestId("matter-submit-button").click();
  await expect(page.getByTestId("new-matter-dialog")).toBeHidden();
  // creating a matter returns to the list; the person opens it from there
  await page.getByTestId("matter-row").filter({ hasText: title }).click();
  await expect(page.getByTestId("matter-title")).toContainText(title);
}

test("sign out, sign back in, and a wrong password is refused without saying which part was wrong", async ({ page }) => {
  const u = await signUp(page);
  await skipTour(page);
  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out-button").click();
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/matters"); // signed out: the app sends the person to sign in rather than showing an empty page
  await expect(page).toHaveURL(/\/login/);

  await page.getByTestId("auth-email-input").fill(u.email);
  await page.getByTestId("auth-password-input").fill(u.password + "x");
  await page.getByTestId("auth-submit-button").click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("auth-form")).not.toContainText(u.email); // the message must not echo or confirm the account

  await page.getByTestId("auth-password-input").fill(u.password);
  await page.getByTestId("auth-submit-button").click();
  // regression: turned away from a private page while signed out, then signing in, once left the person on the sign-in screen (a cached "not signed in" was reused)
  await expect(page.getByTestId("start-greeting")).toBeVisible();
  await expect(page).toHaveURL(/\/start/);
});

test("an expired session sends the person to sign in and shows nothing private", async ({ page, context }) => {
  await signUp(page);
  await skipTour(page);
  await context.clearCookies(); // what an expired or revoked session looks like to the browser
  await page.goto("/matters");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("matter-row")).toHaveCount(0);
});

test("a matter is created, and a fact and a timeline event are added and listed", async ({ page }) => {
  await signUp(page);
  await skipTour(page);
  const title = `Supply dispute ${Date.now().toString(36)}`;
  await newMatter(page, title);

  await page.goto("/matters");
  await expect(page.getByTestId("matter-row").filter({ hasText: title })).toHaveCount(1);
  await page.getByTestId("matter-row").filter({ hasText: title }).click();
  await expect(page.getByTestId("matter-title")).toContainText(title);

  await page.getByTestId("tab-timeline").click();
  await page.getByTestId("event-date-input").fill("2026-08-02");
  await page.getByTestId("event-description-input").fill("Goods supplied under invoice 118");
  await page.getByTestId("add-event-button").click();
  await expect(page.getByTestId("timeline-row")).toContainText("Goods supplied under invoice 118");
  await scan(page, "matter timeline");
});

test("one person cannot open another person's matter by its address", async ({ browser, page }) => {
  await signUp(page);
  await skipTour(page);
  const title = `Private matter ${Date.now().toString(36)}`;
  await newMatter(page, title);
  const url = page.url();

  const other = await browser.newContext();
  const p2 = await other.newPage();
  await signUp(p2, newUser());
  await p2.goto(url);
  await expect(p2.getByText(title)).toHaveCount(0);
  await other.close();
});

test("an error from the server is shown in words and the screen stays usable", async ({ page }) => {
  await signUp(page);
  await skipTour(page);
  await page.route("**/api/matters", (route) => (route.request().method() === "GET" ? route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Something went wrong on our side." }) }) : route.continue()));
  await page.goto("/matters");
  await expect(page.getByTestId("new-matter-button")).toBeVisible(); // the page did not go blank
  await expect(page.locator("body")).not.toContainText("undefined");
  await expect(page.locator("body")).not.toContainText("[object Object]");
});

test("on a phone-sized screen the main screens fit without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await skipTour(page);
  for (const path of ["/", "/matters", "/templates", "/legal", "/settings", "/start", "/recovery", "/research", "/deadlines", "/ask", "/dashboard"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `sideways overflow on ${path}`).toBeLessThanOrEqual(1);
  }
});

test("on a phone the bar has four main actions plus More, and everything else (Legal Recovery included) is under More", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await skipTour(page);
  await expect(page.getByTestId("mobile-nav").locator("a")).toHaveCount(4); // Home, Legal Intelligence, Legal Katalyst, Dates
  await expect(page.getByTestId("mobile-nav-intelligence")).toBeVisible();
  await expect(page.getByTestId("mobile-nav-toolkit")).toBeVisible();
  await page.getByTestId("mobile-nav-more").click();
  for (const id of ["more-recovery", "more-settings", "more-help", "more-signout"]) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByTestId("more-recovery-sub")).toHaveText("Recover unpaid dues: free portal first, legal notice next.");
  await expect(page.getByTestId("more-research")).toHaveCount(0); // Research is a main part of Legal Intelligence now
  await expect(page.getByTestId("more-ask")).toHaveCount(0);
  await expect(page.getByTestId("more-switcher")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("more-sheet")).toHaveCount(0);
});

test("the sign-in form can be completed with the keyboard alone", async ({ page }) => {
  const u = await signUp(page);
  await skipTour(page);
  await page.getByTestId("account-menu").click();
  await page.getByTestId("sign-out-button").click();
  await page.goto("/login");
  await page.getByTestId("auth-email-input").focus();
  await page.keyboard.type(u.email);
  await page.keyboard.press("Tab");
  await page.keyboard.type(u.password);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("start-greeting")).toBeVisible();
});

test("the matter overview shows the description that was typed and counts what the matter holds", async ({ page }) => {
  await signUp(page);
  await skipTour(page);
  const title = `Overview ${Date.now().toString(36)}`;
  await page.goto("/matters");
  await page.getByTestId("new-matter-button").click();
  await page.getByTestId("matter-title-input").fill(title);
  await page.getByTestId("matter-parties-input").fill("A v. B");
  await page.getByTestId("matter-description-input").fill("Goods delivered in March; payment not received.");
  await page.getByTestId("matter-submit-button").click();
  await page.getByTestId("matter-row").filter({ hasText: title }).click();
  await expect(page.getByTestId("matter-description")).toHaveText("Goods delivered in March; payment not received.");
  await expect(page.getByTestId("count-facts")).toContainText("0 recorded");

  await page.getByTestId("tab-facts").click();
  await page.getByTestId("fact-value-input").fill("Invoice 118 was raised on 2 March");
  await page.getByTestId("add-fact-button").click();
  await page.getByTestId("tab-timeline").click();
  await page.getByTestId("event-date-input").fill("2026-03-02");
  await page.getByTestId("event-description-input").fill("Invoice 118 raised");
  await page.getByTestId("add-event-button").click();
  await expect(page.getByTestId("timeline-row")).toBeVisible();
  await page.getByTestId("tab-overview").click();
  await expect(page.getByTestId("count-facts")).toContainText("1 recorded");
  await expect(page.getByTestId("count-timeline")).toContainText(": 1");
});

test("a matter's details can be edited later; Telugu, symbols and long text survive a reload and show in the list", async ({ page }) => {
  await signUp(page);
  await skipTour(page);
  const title = `Edit ${Date.now().toString(36)}`;
  await page.goto("/matters");
  await page.getByTestId("new-matter-button").click();
  await page.getByTestId("matter-title-input").fill(title);
  await page.getByTestId("matter-parties-input").fill("A v. B");
  await page.getByTestId("matter-submit-button").click();
  await page.getByTestId("matter-row").filter({ hasText: title }).click();
  await expect(page.getByTestId("matter-description")).toHaveText("No description recorded.");

  const text = "ఇది ఒక వివరణ — రూ. 5,00,000 “quotes” & <b>x</b>\nsecond line " + "long ".repeat(400);
  await page.getByTestId("matter-edit-details").click();
  await page.getByTestId("matter-edit-description").fill(text);
  await page.getByTestId("matter-edit-parties").fill("Ravi v. Sita Traders");
  await page.getByTestId("matter-edit-save").click();
  await expect(page.getByTestId("matter-details-form")).toBeHidden();
  await expect(page.getByTestId("matter-description")).toContainText("ఇది ఒక వివరణ");

  await page.reload(); // saved on the server, not just on screen
  await expect(page.getByTestId("matter-description")).toContainText("రూ. 5,00,000 “quotes” & <b>x</b>");
  await expect(page.getByTestId("matter-description")).toContainText("long long long");
  await expect(page.getByText("Ravi v. Sita Traders")).toBeVisible();

  await page.goto("/matters");
  await expect(page.getByTestId("matter-row").filter({ hasText: title }).getByTestId("matter-row-description")).toContainText("ఇది ఒక వివరణ");
});
