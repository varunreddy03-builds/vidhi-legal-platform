import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// "Check this draft": a template draft with faults put in on purpose, the list of flags, a click that lands on the place in the text, on a desktop and on a phone.
const VALUES = {
  notice_date: "2026-11-05", sender_name: "Ravi Kumar", sender_address: "12 Mill Road, Guntur", recipient_name: "Asha Traders", recipient_address: "4 Market Street, Vijayawada",
  debt_description: "Goods supplied in March", cheque_number: "004512", cheque_date: "2026-08-01", cheque_amount: "125000", drawn_on_bank: "Example Bank, Guntur branch",
  presented_on: "2026-08-10", returned_on: "2026-08-12", return_reason: "Funds insufficient", payment_period_days: "15",
};

async function brokenDraft(page: import("@playwright/test").Page) {
  await signUp(page);
  const d = await (await page.request.post("/api/templates/in-cheque-return-legal-notice/draft", { data: { values: VALUES } })).json();
  const body = d.body.replace("Asha Traders", "the other side").replace("Rs 1,25,000", "Rs 1,52,000");
  await page.goto(`/drafts/${d.id}`);
  await expect(page.getByTestId("draft-editor-body")).toHaveValue(d.body);
  await page.getByTestId("draft-editor-body").fill(body);
  return { id: d.id as string, body };
}

test("a broken template draft is flagged, each flag jumps to its place, and nothing is changed", async ({ page }) => {
  const { body } = await brokenDraft(page);
  await page.getByTestId("draft-check-button").click();
  await expect(page.getByTestId("draft-check-result")).toBeVisible();
  const items = page.getByTestId("draft-check-item");
  await expect(items.first()).toBeVisible();
  const codes = await items.evaluateAll((els) => els.map((e) => e.getAttribute("data-code")));
  expect(codes).toEqual(expect.arrayContaining(["open_item", "party_missing", "amount_unknown"]));
  expect(await page.getByTestId("draft-check-summary").innerText()).toMatch(/\d+ to fix, \d+ to look at/);

  await page.locator('[data-testid="draft-check-item"][data-code="amount_unknown"]').first().click();
  const selected = await page.getByTestId("draft-editor-body").evaluate((el: HTMLTextAreaElement) => el.value.slice(el.selectionStart, el.selectionEnd));
  expect(selected).toBe("Rs 1,52,000");
  expect(await page.getByTestId("draft-editor-body").inputValue()).toBe(body); // checking does not touch the text
  await scan(page, "draft with check list");
});

test("a clean draft says nothing was found, on a phone too", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  const d = await (await page.request.post("/api/drafts", { data: { title: "Plain letter", body: "Dear sir, please pay the amount due." } })).json();
  await page.goto(`/drafts/${d.id}`);
  await page.getByTestId("draft-check-button").click();
  await expect(page.getByTestId("draft-check-summary")).toContainText("Nothing found");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("a flagged item can be fixed by hand and the next check no longer lists it", async ({ page }) => {
  const { id } = await brokenDraft(page);
  await page.getByTestId("draft-check-button").click();
  await page.locator('[data-testid="draft-check-item"][data-code="party_missing"]').first().waitFor();
  const text = (await page.getByTestId("draft-editor-body").inputValue()).replace("the other side", "Asha Traders").replace("Rs 1,52,000", "Rs 1,25,000");
  await page.getByTestId("draft-editor-body").fill(text);
  await page.getByTestId("draft-check-button").click();
  await expect(page.locator('[data-testid="draft-check-item"][data-code="party_missing"]')).toHaveCount(0);
  await expect(page.locator('[data-testid="draft-check-item"][data-code="amount_unknown"]')).toHaveCount(0);
  const saved = await (await page.request.get(`/api/drafts/${id}`)).json();
  expect(saved.version).toBe(1); // the check saved nothing
});
