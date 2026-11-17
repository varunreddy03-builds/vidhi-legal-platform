import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers";

const SENTENCE = "This app provides drafting help and general information. It is not legal advice.";

async function answer(page: Page, ids: string[]) {
  for (const id of ids) await page.getByTestId(id).click();
}

test.use({ viewport: { width: 375, height: 812 } });

test("Legal Recovery guide: eligible business sees the free portal first, status is saved and resumes, notice is made from the template, and escalation is recorded", async ({ page }) => {
  await signUp(page);
  await page.goto("/recovery/guide");
  await expect(page.getByTestId("guide-disclaimer")).toHaveText(SENTENCE);
  await expect(page.getByTestId("guide-udyam-note")).toContainText("VIDHI does not check this");
  await answer(page, ["guide-a-yes", "guide-a-business", "guide-a-docs-yes", "guide-a-over45"]);
  await expect(page.getByTestId("guide-disclaimer")).toHaveText(SENTENCE); // on every step
  await page.getByTestId("guide-amount").fill("52000");
  await page.getByTestId("guide-amount-next").click();
  await page.getByTestId("guide-seller-name").fill("Invented Traders");
  await page.getByTestId("guide-buyer-name").fill("Invented Buyer Ltd");
  await page.getByTestId("guide-who-next").click();

  // step 2: the free portal comes first for a registered small business selling to a business
  await expect(page.getByTestId("guide-portal-card")).toBeVisible();
  await expect(page.getByTestId("guide-portal-card")).toContainText("Start with the free government MSME ODR portal.");
  await expect(page.getByTestId("guide-portal-open")).toHaveAttribute("href", /^https:\/\//);
  await expect(page.getByTestId("guide-last-verified")).toContainText("Last verified");
  await expect(page.getByTestId("guide-last-verified")).toContainText("not yet checked against the official source");
  await expect(page.getByTestId("guide-portal-card").getByTestId("todo-verify").first()).toBeVisible(); // every unconfirmed legal fact on the card carries the mark
  expect(await page.getByTestId("guide-portal-card").getByTestId("todo-verify").count()).toBeGreaterThanOrEqual(4);
  await expect(page.getByTestId("guide-progress").locator("li")).toHaveCount(4);
  await expect(page.getByTestId("guide-self-declared")).toContainText("does not check this with the portal"); // it is the person's own word, and the screen says so
  await page.getByTestId("guide-portal-ref").fill("MSME/2026/INVENTED-1");
  await page.getByTestId("guide-portal-filed").click();
  await expect(page.getByTestId("guide-status")).toHaveText("You said: Portal filed · MSME/2026/INVENTED-1");

  // leave and come back: it resumes with the saved status and the first question's answer kept
  const url = page.url();
  expect(url).toMatch(/\/recovery\/guide\/[0-9a-f-]+$/);
  await page.goto("/recovery");
  await expect(page.getByTestId("recovery-case-stage").first()).toHaveText("Portal filed");
  await page.getByTestId("recovery-case-row").first().click();
  await expect(page).toHaveURL(url);
  await expect(page.getByTestId("guide-status")).toContainText("You said: Portal filed");

  // step 3: the notice, from the template
  await page.getByTestId("guide-to-notice").click();
  await expect(page.getByTestId("guide-form")).toContainText("Send a legal notice if the portal does not apply");
  await page.getByTestId("guide-seller-address").fill("1 Market Road, Pune");
  await page.getByTestId("guide-buyer-address").fill("9 Lake View, Mumbai");
  await page.getByTestId("guide-invoice-number").fill("INV-7");
  await page.getByTestId("guide-invoice-date").fill("2026-06-01");
  await page.getByTestId("guide-due-date").fill("2026-08-01");
  await page.getByTestId("guide-description").fill("rolled steel");
  await expect(page.getByTestId("guide-make-notice")).toBeDisabled(); // the confirmation box is required first
  await page.getByTestId("guide-confirm-details").check();
  await page.getByTestId("guide-make-notice").click();
  await expect(page.getByTestId("guide-notice-text")).toContainText("invoice INV-7");
  await expect(page.getByTestId("guide-notice-text")).toContainText("52,000"); // the statement of account is written by the server
  await expect(page.getByTestId("guide-email-note")).toContainText("may not be accepted as formal service");
  await expect(page.getByTestId("guide-lawyer")).toBeVisible();

  // delivery: the person downloads it and says they sent it
  await page.getByTestId("guide-mark-downloaded").click();
  await expect(page.getByTestId("guide-sent")).toContainText("Notice sent");
  await expect(page.getByTestId("guide-sent-method")).toHaveText("Download and send it yourself");
  await expect(page.getByTestId("guide-status")).toContainText("You said: Notice sent");

  // step 4: still unpaid
  await expect(page.getByTestId("guide-escalate-card")).toContainText("Talk to a lawyer about recovery through court or arbitration");
  await page.getByTestId("guide-mark-escalated").click();
  await expect(page.getByTestId("guide-escalated")).toBeVisible();
  await page.goto("/recovery");
  await expect(page.getByTestId("recovery-case-stage").first()).toHaveText("Escalated");

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("Legal Recovery guide: an individual buyer or an unregistered seller skips the portal with a reason, and 'not sure' gets the Udyam explainer", async ({ page }) => {
  await signUp(page);
  const run = async (first: string, second: string) => {
    await page.goto("/recovery/guide");
    await answer(page, [first, second, "guide-a-docs-no", "guide-a-under15"]);
    await page.getByTestId("guide-amount").fill("1000");
    await page.getByTestId("guide-amount-next").click();
    await page.getByTestId("guide-seller-name").fill("Invented Seller");
    await page.getByTestId("guide-buyer-name").fill("Invented Buyer");
    await page.getByTestId("guide-who-next").click();
  };
  await run("guide-a-yes", "guide-a-individual");
  await expect(page.getByTestId("guide-portal-card")).toHaveCount(0);
  await expect(page.getByTestId("guide-skip-reason")).toContainText("individual consumer");
  await expect(page.getByTestId("guide-skip-reason").getByTestId("todo-verify")).toBeVisible();
  await run("guide-a-no", "guide-a-business");
  await expect(page.getByTestId("guide-portal-card")).toHaveCount(0);
  await expect(page.getByTestId("guide-skip-reason")).toContainText("not registered");
  await run("guide-a-notsure", "guide-a-business");
  await expect(page.getByTestId("guide-unsure")).toContainText("Udyam registration");
  await expect(page.getByTestId("guide-to-notice")).toBeVisible();
});
