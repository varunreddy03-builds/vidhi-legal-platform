import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Client records (frontend/src/pages/Clients.tsx): add, search, edit, link to a matter, and deletion that waits for the matter to be unlinked.
test("a firm can keep client records, link a matter to one, and cannot delete a client that still has a matter", async ({ page }) => {
  await signUp(page);
  await page.goto("/clients");
  await expect(page.getByTestId("clients-page")).toBeVisible();
  await expect(page.getByText("No clients yet.")).toBeVisible();

  await page.getByTestId("client-add").click();
  await page.getByTestId("client-name").fill("Acme Traders Pvt Ltd");
  await page.getByTestId("client-kind").selectOption("COMPANY");
  await page.getByTestId("client-email").fill("legal@acme.example");
  await page.getByTestId("client-notes").fill("Prefers calls after 5 pm.");
  await page.getByTestId("client-save").click();
  const detail = page.getByTestId("client-detail");
  await expect(detail).toContainText("Acme Traders Pvt Ltd");
  await expect(detail).toContainText("Prefers calls after 5 pm.");
  await expect(detail).toContainText("No matters yet");

  // search finds it, a wrong search does not
  await page.getByTestId("client-search").fill("acme.example");
  await expect(page.getByTestId("client-row")).toHaveCount(1);
  await page.getByTestId("client-search").fill("zzz-nobody");
  await expect(page.getByText("No client matches that search.")).toBeVisible();
  await page.getByTestId("client-search").fill("");

  // link a matter to the client from the matter's own details
  const m = await (await page.request.post("/api/matters", { data: { title: "Acme v Beta", parties: "Acme v Beta", description: "A dispute." } })).json();
  await page.goto(`/matters/${m.id}`);
  await page.getByTestId("matter-edit-details").click();
  await page.getByTestId("matter-edit-client").selectOption({ label: "Acme Traders Pvt Ltd" });
  await page.getByTestId("matter-edit-save").click();
  await expect(page.getByText("Matter details saved")).toBeVisible();

  await page.goto("/clients");
  await page.getByTestId("client-row").first().click();
  await expect(page.getByTestId("client-detail")).toContainText("Acme v Beta");
  await expect(page.getByTestId("client-row").first()).toContainText("1 matter");

  // delete is refused while the matter is linked (the confirm button stays disabled)
  await page.getByTestId("client-delete").click();
  await expect(page.getByText("Matters are still linked to this client")).toBeVisible();
  await scan(page, "client records");
});

test("a client record can be edited", async ({ page }) => {
  await signUp(page);
  await page.request.post("/api/clients", { data: { name: "Ramesh Kumar" } });
  await page.goto("/clients");
  await page.getByTestId("client-row").first().click();
  await page.getByTestId("client-edit").click();
  await page.getByTestId("client-phone").fill("+91 98000 00000");
  await page.getByTestId("client-save").click();
  await expect(page.getByTestId("client-detail")).toContainText("+91 98000 00000");
});
