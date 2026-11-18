import { expect, test } from "@playwright/test";
import { newUser, scan } from "./helpers";

// The first five minutes for a new lawyer, on a 375 px phone: sign up, try Authority Check on the made-up sample draft, read the result and what its labels mean.
// It counts the person's actions (typing a field, ticking a box, pressing a button or link) and times the path. The 1.5 s pause before the sign-up button is the server's bot check, not the app being slow.
test.skip(process.env.AUTHORITY_CHECK_ENABLED !== "true", "Authority Check is off on this server");

test("a new lawyer reaches an Authority Check result on a phone in a few steps, with the labels explained", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const u = newUser();
  let actions = 0;
  const t0 = Date.now();

  await page.goto("/login?mode=signup");
  for (const [id, value] of [["auth-fullname-input", u.name], ["auth-org-input", u.org], ["auth-email-input", u.email], ["auth-password-input", u.password]] as const) {
    await page.getByTestId(id).fill(value);
    actions++;
  }
  await page.getByTestId("auth-privacy-checkbox").check();
  actions++;
  await page.waitForTimeout(1500);
  await page.getByTestId("auth-submit-button").click();
  actions++;
  await expect(page.getByTestId("start-greeting")).toBeVisible();
  const signedUpMs = Date.now() - t0;

  // the tour is optional: nothing opens by itself
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await scan(page, "start screen on a phone");

  await expect(page.getByTestId("start-try-authority")).toBeVisible();
  await page.getByTestId("start-try-authority").click();
  actions++;
  await expect(page.getByTestId("authority-text-input")).toHaveValue(/SAMPLE DRAFT - FICTIONAL/);
  await expect(page.getByTestId("authority-title-input")).toHaveValue(/SAMPLE/);
  await page.getByTestId("authority-run").click();
  actions++;
  await expect(page.getByTestId("authority-report")).toBeVisible({ timeout: 30_000 }); // the very first check after the server starts is slower; the whole journey must still finish inside 60 s (below)
  await expect(page.getByTestId("authority-summary")).toContainText("references");
  const doneMs = Date.now() - t0;

  await page.getByTestId("authority-legend").locator("summary").click();
  actions++;
  await expect(page.getByTestId("authority-legend")).toContainText("This is not a finding that the reference is wrong");
  await expect(page.getByTestId("authority-legend")).toContainText("not about the law");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await scan(page, "Authority Check result on a phone");

  console.log(`FIRST-FIVE-MINUTES actions=${actions} signed_up_after_ms=${signedUpMs} result_after_ms=${doneMs}`);
  expect(actions).toBeLessThanOrEqual(10);
  expect(doneMs).toBeLessThan(60_000);
});

test("the sample draft is made up, the button on the form fills it, and nothing is sent until the person presses Check", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  const { signUp } = await import("./helpers");
  await signUp(page);
  const sent: string[] = [];
  page.on("request", (r) => r.method() === "POST" && r.url().includes("/api/authority/checks") && sent.push(r.url()));
  await page.goto("/katalyst/authority");
  await expect(page.getByTestId("authority-text-input")).toHaveValue("");
  await page.getByTestId("authority-use-sample").click();
  await expect(page.getByTestId("authority-text-input")).toHaveValue(/Every name, case and Act below is invented/);
  expect(sent).toEqual([]);
});
