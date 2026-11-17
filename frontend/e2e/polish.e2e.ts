import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

async function skipTour(page: import("@playwright/test").Page) {
  await expect(page.getByTestId("guided-tour")).toHaveCount(0); // the tour no longer opens by itself
}

test("sign-in shows Google first, a clear cancelled message, and no fake login", async ({ page }) => {
  await page.goto("/login?error=google_cancelled");
  await expect(page.getByTestId("auth-google-button")).toBeVisible();
  await expect(page.getByTestId("auth-error")).toContainText(/cancelled/i);
  await expect(page.getByTestId("auth-error")).toHaveAttribute("role", "alert");
  // the Google link goes to the server's own OAuth start, never to a local pretend page
  await expect(page.getByTestId("auth-google-button")).toHaveAttribute("href", "/api/auth/google/start");
  await page.goto("/login?error=google_failed");
  await expect(page.getByTestId("auth-error")).toContainText(/did not work/i);
  await expect(page).toHaveURL(/\/login/);
});

test("a wrong password is explained inline on the sign-in screen", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("auth-email-input").fill("nobody@example.com");
  await page.getByTestId("auth-password-input").fill("not-the-password-1");
  await page.getByTestId("auth-submit-button").click();
  await expect(page.getByTestId("auth-error")).toBeVisible();
  await expect(page.getByTestId("auth-form")).not.toContainText("nobody@example.com");
});

test.describe("phone width (375px)", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("sign-in has no accessibility problems and no sideways scroll", async ({ page }) => {
    for (const path of ["/login", "/login?mode=signup", "/login?error=google_failed", "/forgot-password"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await scan(page, `${path} @375`);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  });

  test("signed-in screens keep the five-slot bar", async ({ page }) => {
    await signUp(page);
    await expect(page.getByTestId("guided-tour")).toHaveCount(0); // no full-screen box over the first screen on a phone
    await expect(page.getByTestId("mobile-nav")).toBeVisible();
    await page.goto("/matters");
    await page.waitForLoadState("networkidle");
    await scan(page, "/matters @375");
    await page.goto("/recovery");
    await page.waitForLoadState("networkidle");
    await scan(page, "/recovery @375");
    await page.goto("/settings");
    await page.waitForLoadState("networkidle");
    await scan(page, "/settings @375");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});

test.describe("phone width: Legal Recovery lives under More (375px)", () => {
  test.use({ viewport: { width: 375, height: 812 } });

  test("Legal Recovery opens from More, its guide starts, and the bar stays the same", async ({ page }) => {
    await signUp(page);
    await page.getByTestId("mobile-nav-more").click();
    await page.getByTestId("more-recovery").click();
    await expect(page).toHaveURL(/\/recovery$/);
    await expect(page.getByTestId("recovery-hero")).toBeVisible();
    await page.getByTestId("start-recovery-button").click();
    await expect(page).toHaveURL(/\/recovery\/guide$/); // every new recovery starts in the guide, not a one-step form
    await expect(page.getByTestId("guide-q1")).toBeVisible();
    // the old address that opened the one-step form now opens the guide
    await page.goto("/recovery?new=1");
    await expect(page).toHaveURL(/\/recovery\/guide$/);
    // one bar everywhere: Dates keeps it, and Legal Katalyst is in it
    await page.getByTestId("mobile-nav-dates").click();
    await expect(page).toHaveURL(/deadlines/);
    await expect(page.getByTestId("mobile-nav-toolkit")).toBeVisible();
  });
});

test("Legal Katalyst shows Authority Check and the list of dates and the pre-filing defect check and the old-code checker and the deadline engine as ready or not switched on, with no fake buttons", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await expect(page.getByTestId("toolkit-title")).toBeVisible();
  const on = process.env.AUTHORITY_CHECK_ENABLED === "true"; // the test server is started with the feature on or off
  await expect(page.getByTestId("toolkit-authority-state")).toHaveText(on ? /ready/i : /not switched on/i);
  const datesOn = process.env.DATE_LIST_ENABLED === "true";
  await expect(page.getByTestId("toolkit-dates-state")).toHaveText(datesOn ? /ready/i : /not switched on/i);
  const defectsOn = process.env.DEFECT_CHECK_ENABLED === "true";
  await expect(page.getByTestId("toolkit-defects-state")).toHaveText(defectsOn ? /ready/i : /not switched on/i);
  const oldcodeOn = process.env.OLD_CODE_CHECK_ENABLED === "true";
  await expect(page.getByTestId("toolkit-oldcode-state")).toHaveText(oldcodeOn ? /ready/i : /not switched on/i);
  const deadlinesOn = process.env.DEADLINE_ENGINE_ENABLED === "true";
  await expect(page.getByTestId("toolkit-deadlines-state")).toHaveText(deadlinesOn ? /ready/i : /not switched on/i);
  await expect(page.getByTestId("toolkit-list").locator("a, button")).toHaveCount((on ? 1 : 0) + (datesOn ? 1 : 0) + (defectsOn ? 1 : 0) + (oldcodeOn ? 1 : 0) + (deadlinesOn ? 1 : 0));
  await page.goto("/ask");
  await expect(page).toHaveURL(/\/ask$/); // Ask a question is back under Legal Intelligence
  await expect(page.getByTestId("ask-input")).toBeVisible();
});

test("Home has one question box and two doors (Legal Intelligence and Legal Katalyst), and Legal Recovery is not on it", async ({ page }) => {
  await signUp(page);
  await skipTour(page);
  await page.goto("/start");
  await expect(page.getByTestId("start-intelligence")).toBeVisible();
  await expect(page.getByTestId("start-toolkit")).toBeVisible();
  await expect(page.locator("main").getByText("Legal Recovery")).toHaveCount(0); // it is not on the home screen; it is under More
  await page.getByTestId("start-ask-input").fill("What should I check before signing a rent agreement?");
  await page.getByTestId("start-ask-submit").click();
  await expect(page).toHaveURL(/\/ask\?q=/);
  await expect(page.getByTestId("ask-input")).toHaveValue("What should I check before signing a rent agreement?");
  await page.goto("/intelligence");
  for (const id of ["research", "matters", "drafts"]) await expect(page.getByTestId(`intel-${id}`)).toBeVisible();
  await expect(page.getByTestId("intel-ask")).toHaveCount(0); // no "Ask a question" tile (owner, 2026-10-31)
  await expect(page.getByTestId("nav-ask")).toHaveCount(0); // and no menu item
});

test.describe("phone with a camera cut-out or dynamic island (375px)", () => {
  test.use({ viewport: { width: 375, height: 812 } });
  const INSET = 48; // what an Android WebView reports through --safe-area-inset-top

  test("the sign-in controls and the app header stay clear of the top inset", async ({ page }) => {
    const setInset = () => page.evaluate((px) => document.documentElement.style.setProperty("--safe-area-inset-top", `${px}px`), INSET);
    await page.goto("/login");
    await setInset();
    const theme = page.getByRole("button").first();
    await expect(theme).toBeVisible();
    for (const b of await page.getByRole("button").all()) {
      const box = await b.boundingBox();
      if (box && box.y < 200) expect(box.y, "a control under the status bar").toBeGreaterThanOrEqual(INSET - 1);
    }
    await signUp(page);
    await setInset();
    const header = page.locator("header").first();
    await expect(header).toBeVisible();
    expect((await header.boundingBox())!.y).toBeGreaterThanOrEqual(INSET - 1);
    await page.goto("/matters");
    await setInset();
    await page.evaluate(() => window.scrollTo(0, 400));
    expect((await page.locator("header").first().boundingBox())!.y).toBeGreaterThanOrEqual(INSET - 1); // still clear of the inset after scrolling
  });
});

test("the public home page shows the five Legal Katalyst tools, and Legal Recovery only as a small note", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("home-toolkit")).toBeVisible();
  for (const id of ["authority", "deadlines", "oldcode", "defects", "dates"]) await expect(page.getByTestId(`home-tool-${id}`)).toBeVisible();
  await expect(page.getByTestId("home-tool-dates")).toContainText("List of dates with page references");
  await expect(page.getByTestId("division-card-recovery")).toHaveCount(0);
  await expect(page.getByTestId("division-card-intelligence")).toHaveCount(0);
  await expect(page.getByTestId("home-recovery-note")).toContainText("under More");
});
