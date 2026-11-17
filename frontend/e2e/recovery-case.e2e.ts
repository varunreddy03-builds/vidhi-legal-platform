import { expect, test, type Page } from "@playwright/test";
import { scan, signUp } from "./helpers";

async function newCase(page: Page, handoff: boolean) {
  const made = await page.request.post("/api/recovery/cases", { data: { creditor_name: "Acme Traders", debtor_name: "Beta Stores", amount: 50000 } });
  expect(made.ok()).toBeTruthy();
  const id = (await made.json()).id as string;
  if (handoff) expect((await page.request.post(`/api/recovery/cases/${id}/handoff`)).ok()).toBeTruthy();
  return id;
}

async function openDelete(page: Page, id: string) {
  await page.goto(`/recovery/cases/${id}`);
  await page.getByText("More options: reminders, mark as paid, delete").click();
  await page.getByTestId("delete-case").click();
  await expect(page.getByTestId("confirm-delete-button")).toBeDisabled(); // nothing is deleted until the word is typed
}

test("deleting a case that was handed to a lawyer says the lawyer's matter stays, and the matter does stay", async ({ page }) => {
  await signUp(page);
  const id = await newCase(page, true);
  await openDelete(page, id);
  await expect(page.getByRole("dialog")).toContainText("is NOT deleted");
  await scan(page, "recovery delete dialog");
  await page.getByTestId("confirm-delete-input").fill("DELETE");
  await page.getByTestId("confirm-delete-button").click();
  await expect(page).toHaveURL(/\/recovery$/);

  expect((await page.request.get(`/api/recovery/cases/${id}`)).status()).toBe(404);
  await page.goto("/matters");
  await expect(page.getByTestId("matter-row").filter({ hasText: "Recovery: Acme Traders vs Beta Stores" })).toHaveCount(1);
});

test("deleting a case that was never handed over does not mention a lawyer's matter", async ({ page }) => {
  await signUp(page);
  const id = await newCase(page, false);
  await openDelete(page, id);
  await expect(page.getByRole("dialog")).not.toContainText("NOT deleted");
  await page.getByTestId("confirm-delete-input").fill("delete"); // the word must match exactly
  await expect(page.getByTestId("confirm-delete-button")).toBeDisabled();
});
