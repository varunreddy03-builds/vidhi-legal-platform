import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// The Vault: a matter that holds many documents, a summary of each, and one review table. The checking rules (quote looked up by the program, page from the program) are tested in
// backend/tests/test_vault.py; here the model is the test stub, so this proves the screens and the flow, not the answers.

const lease = (n: string) => `LEASE AGREEMENT ${n}\nThis lease is made between Asha Rao (the landlord) and Ravi Kumar (the tenant).\nEither party may end this lease by giving sixty days written notice.\n`;

test("a Vault takes several files, fills a table, and stays out of the Matters list", async ({ page }) => {
  await signUp(page);
  await page.goto("/vault");
  await expect(page.getByTestId("vault-empty")).toBeVisible();
  const name = `Leases ${unique()}`;
  await page.getByTestId("vault-title-input").fill(name);
  await page.getByTestId("vault-create-button").click();
  await expect(page.getByTestId("vault-name")).toHaveText(name);

  await page.getByTestId("vault-file-input").setInputFiles([
    { name: `lease-a-${unique()}.txt`, mimeType: "text/plain", buffer: Buffer.from(lease(unique())) },
    { name: `lease-b-${unique()}.txt`, mimeType: "text/plain", buffer: Buffer.from(lease(unique())) },
  ]);
  await expect(page.getByTestId("vault-doc-count")).toHaveText("2 documents");
  await expect(page.getByTestId("vault-summary-item")).toHaveCount(2);
  await scan(page, "Vault with two files");

  // The browser tests run the model as a stub with no scripted replies, so the table's rows are answered here (the server's checking is tested in backend/tests/test_vault.py).
  const cols = [{ id: "parties", label: "Parties", question: "q" }, { id: "c1", label: "Who is the landlord?", question: "Who is the landlord?" }];
  const rows: unknown[] = [];
  await page.route("**/api/matters/*/vault/rows", async (route) => {
    const req = route.request();
    if (req.method() === "POST") {
      const body = req.postDataJSON() as { document_id: string };
      const row = { id: body.document_id, document_id: body.document_id, filename: `file-${rows.length + 1}.txt`, read_in_full: true, coverage_note: "", cells: [
        { id: "parties", status: "FOUND", answer: "Asha Rao and Ravi Kumar", quote: "between Asha Rao (the landlord) and Ravi Kumar", page: 1, note: "n" },
        { id: "c1", status: "UNCONFIRMED", answer: "Asha Rao", quote: "", page: null, note: "n" }] };
      rows.push(row);
      await route.fulfill({ json: row });
    } else if (req.method() === "GET") {
      await route.fulfill({ json: { rows, columns: cols, documents_total: 2, documents_with_text: 2, note: "Each answer carries a quote." } });
    } else await route.continue();
  });
  await page.getByTestId("vault-custom-input").fill("Who is the landlord?");
  await page.getByTestId("vault-custom-add").click();
  await page.getByTestId("vault-run").click();
  await expect(page.getByTestId("vault-row")).toHaveCount(2, { timeout: 60_000 });
  await expect(page.getByTestId("vault-cell-FOUND").first()).toContainText("page 1");
  await expect(page.getByTestId("vault-cell-UNCONFIRMED").first()).toContainText("Unconfirmed");
  await expect(page.getByTestId("vault-csv")).toHaveAttribute("href", /\/vault\/table\.csv$/);
  await scan(page, "Vault with the review table filled");

  // a Vault is not listed among ordinary matters, but is listed in the Vault list
  await page.goto("/matters");
  await expect(page.getByText(name)).toHaveCount(0);
  await page.goto("/vault");
  await expect(page.getByTestId("vault-item").filter({ hasText: name })).toHaveCount(1);

  await page.goto(`/vault`);
  await page.getByTestId("vault-item").filter({ hasText: name }).click();
  await expect(page.getByTestId("vault-name")).toHaveText(name);
});

test("the Vault fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/vault");
  await page.getByTestId("vault-title-input").fill(`Phone ${unique()}`);
  await page.getByTestId("vault-create-button").click();
  await expect(page.getByTestId("vault-name")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(0);
  await scan(page, "Vault on a phone");
});
