import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

test("a new person signs up, can open the tour when they want it, and generates a legal notice from a template", async ({ page }) => {
  const u = await signUp(page);

  // the tour does not pop over the first screen; it opens from the link on Home, in plain words, and can be skipped
  const tour = page.getByTestId("guided-tour");
  await expect(tour).toHaveCount(0);
  await scan(page, "home");
  await page.getByTestId("start-tour").click();
  await expect(tour).toBeVisible();
  await expect(tour).toContainText("VIDHI helps you organise matters");
  await page.getByTestId("tour-skip").click();
  await expect(tour).toBeHidden();

  // the signed-in person is who they said they were
  await page.goto("/settings");
  await expect(page.getByText(u.email).first()).toBeVisible();

  // notice generation: the cheque-return legal notice, filled in by code from the answers
  await page.goto("/templates");
  await page.getByTestId("template-card").filter({ hasText: "cheque returned unpaid" }).click();
  await expect(page.getByTestId("template-form")).toContainText("Not reviewed by a lawyer");
  const answers: Record<string, string> = {
    notice_date: "2026-11-05", sender_name: "Acme Traders", sender_address: "12 Market Road, Pune", recipient_name: "Beta Stores", recipient_address: "4 Mill Lane, Nashik",
    debt_description: "Goods supplied under invoice 118 dated 2 August 2026", cheque_number: "004512", cheque_date: "2026-09-20", cheque_amount: "185000",
    drawn_on_bank: "Example Bank, Nashik branch", presented_on: "2026-09-22", returned_on: "2026-09-24", return_reason: "Funds insufficient", payment_period_days: "15",
  };
  for (const [key, value] of Object.entries(answers)) await page.getByTestId(`tpl-${key}`).fill(value);
  await scan(page, "template form");
  await page.getByTestId("template-create").click();

  await expect(page).toHaveURL(/\/drafts\//);
  await expect(page.getByTestId("template-banner")).toContainText("no lawyer has reviewed");
  const body = page.getByTestId("draft-editor-body");
  await expect(body).toHaveValue(/DRAFT FROM A TEMPLATE - NOT REVIEWED BY A LAWYER/);
  await expect(body).toHaveValue(/LEGAL NOTICE/);
  await expect(body).toHaveValue(/Acme Traders/);
  await expect(body).toHaveValue(/Rs 1,85,000/);
  await expect(body).toHaveValue(/\[LAWYER TO CONFIRM:/); // the points of law are left open, visibly
  await scan(page, "draft with a template banner");
});

test("a missing answer is explained, not silently accepted", async ({ page }) => {
  await signUp(page);
  await page.goto("/templates?t=in-nda");
  await page.getByTestId("tpl-agreement_date").fill("2026-11-05");
  // the browser's own required-field check stops the form until the rest is filled in
  await page.getByTestId("template-create").click();
  await expect(page).toHaveURL(/\/templates/);
  await expect(page.getByTestId("template-form")).toBeVisible();
});