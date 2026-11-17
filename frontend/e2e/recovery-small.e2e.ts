import { expect, test, type Page } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Legal Recovery as the small free helper: the DEFAULT, with the switch RECOVERY_FULL_FLOW off. The e2e server runs with the switch on (so the older Recovery tests keep
// covering the full flow), and this file answers /api/recovery/options itself with "off", which is what the front end hides the extra parts on.
// The backend half (the send route says "not available" when the switch is off) is in backend/tests/test_recovery_mode.py.

async function switchOff(page: Page) {
  await page.route("**/api/recovery/options", (route) => route.fulfill({ json: { full_flow: false } }));
}

async function walk(page: Page, label: string) {
  await switchOff(page);
  await signUp(page);
  await page.goto("/recovery");
  await expect(page.getByTestId("recovery-tagline")).toHaveText("A guide, not legal advice.");
  await scan(page, `Recovery list, empty (${label})`);

  await page.goto("/recovery/guide");
  await expect(page.getByTestId("guide-tagline")).toHaveText("A guide, not legal advice.");
  await expect(page.getByTestId("guide-progress").locator("li")).toHaveCount(3); // no "Lawyer" step
  for (const id of ["guide-a-yes", "guide-a-business", "guide-a-docs-yes", "guide-a-over45"]) await page.getByTestId(id).click();
  await page.getByTestId("guide-amount").fill("52000");
  await page.getByTestId("guide-amount-next").click();
  await page.getByTestId("guide-seller-name").fill("Invented Traders");
  await page.getByTestId("guide-buyer-name").fill("Invented Buyer Ltd");
  await page.getByTestId("guide-who-next").click();

  // the free portal still comes first, with its "last verified" line
  await expect(page.getByTestId("guide-portal-card")).toBeVisible();
  await expect(page.getByTestId("guide-last-verified")).toContainText("Last verified");
  await scan(page, `Recovery portal card (${label})`);
  await page.getByTestId("guide-to-notice").click();

  // the help panel sits above the notice form; every point of law carries "advocate to confirm" and no law is stated
  const help = page.getByTestId("notice-help").first();
  await expect(help).toContainText("How to write a payment notice");
  await help.locator("summary").click();
  await expect(help).toContainText("It is not a court order.");
  await expect(help).toContainText("Registered Post with acknowledgement due");
  await expect(help).toContainText("No threats or insults.");
  await expect(help.getByTestId("advocate-to-confirm")).toHaveCount(4);
  await scan(page, `Recovery notice form with help open (${label})`);

  await page.getByTestId("guide-seller-address").fill("1 Market Road, Pune");
  await page.getByTestId("guide-buyer-address").fill("9 Lake View, Mumbai");
  await page.getByTestId("guide-invoice-number").fill("INV-7");
  await page.getByTestId("guide-invoice-date").fill("2026-06-01");
  await page.getByTestId("guide-due-date").fill("2026-08-01");
  await page.getByTestId("guide-description").fill("rolled steel");
  await page.getByTestId("guide-confirm-details").check();
  await page.getByTestId("guide-make-notice").click();

  // the notice: download and copy are there; email sending and the lawyer steps are not
  await expect(page.getByTestId("guide-notice-text")).toContainText("invoice INV-7");
  await expect(page.getByTestId("notice-help")).toBeVisible();
  await expect(page.getByTestId("guide-download")).toBeVisible();
  await expect(page.getByTestId("guide-copy-text")).toBeVisible();
  for (const hidden of ["guide-email-note", "guide-approve-box", "guide-email-open", "guide-lawyer", "guide-mark-lawyer"]) await expect(page.getByTestId(hidden)).toHaveCount(0);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByTestId("guide-copy-text").click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("INV-7");
  await scan(page, `Recovery notice (${label})`);

  // sent: the three dates the person types are saved; there is no escalation card
  await page.getByTestId("guide-mark-downloaded").click();
  await expect(page.getByTestId("guide-sent")).toContainText("Notice sent");
  await expect(page.getByTestId("guide-escalate-card")).toHaveCount(0);
  await page.getByTestId("guide-track-notice_date").fill("2026-11-01");
  await page.getByTestId("guide-track-due_date").fill("2026-11-16");
  await page.getByTestId("guide-track-next_date").fill("2026-12-01");
  await page.getByTestId("guide-track-save").click();
  await expect(page.getByText("Dates saved")).toBeVisible();
  await scan(page, `Recovery sent with dates (${label})`);
  const url = page.url();
  await page.reload();
  await expect(page.getByTestId("guide-track-next_date")).toHaveValue("2026-12-01"); // kept after leaving and coming back

  // one plain list of claims; the row opens the guide, and the old full-case address does too
  await page.goto("/recovery");
  const row = page.getByTestId("recovery-case-row");
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("Invented Traders");
  await expect(row).not.toContainText("of 5");
  await expect(page.getByTestId("case-next-date")).toContainText("Next date");
  await expect(page.getByTestId("recovery-case-stage")).toHaveText("Notice sent");
  await scan(page, `Recovery list (${label})`);
  const id = url.split("/").pop();
  await page.goto(`/recovery/cases/${id}`);
  await expect(page).toHaveURL(url);
  await expect(page.getByTestId("recovery-guide")).toBeVisible();

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test("small free helper at desktop width: portal first, help panel, notice to download or copy, three dates, one list; no email sending or escalation", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await walk(page, "desktop");
});

test("small free helper at 375px: the same, with no sideways scroll", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await walk(page, "375px");
});
