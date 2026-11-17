import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { unique } from "./helpers";

// The advocate's screen (Admin console > Review law), on an INVENTED Act. The operator account is seeded straight into the test database (scripts/e2e_seed_admin.py).
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const ACT = [
  "THE FICTIONAL PENAL ACT, 1901\n\n1. Short title.—This Act may be called the Fictional Penal Act, 1901.\n\n2. Definitions.—In this Act, unless the context otherwise requires, token means a counter used in Examplia.\n\n3. Hoarding tokens.—Whoever hoards more than one hundred tokens shall be punished with a fine of one unit of Examplia.",
];

let loadedTag = "";
// The invented Acts this test loads would otherwise stay in the shared browser-test database and be found by other tests' searches (the legal lookup test searches the whole library).
test.afterEach(() => {
  if (!loadedTag) return;
  execFileSync(PY, ["-I", "../scripts/e2e_cleanup_legal.py", loadedTag], { env: { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" }, encoding: "utf-8" });
  loadedTag = "";
});

function operatorToken(): string {
  return execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env: { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" }, encoding: "utf-8" }).trim();
}

test("an advocate approves one section and rejects another, under their name; draft text is never shown as reviewed", async ({ page }) => {
  await page.context().addCookies([{ name: "vidhi_session", value: operatorToken(), domain: "localhost", path: "/" }]);
  const t = unique();
  loadedTag = t;
  const title = `Fictional Penal Act ${t}`;
  const src = await (await page.request.post("/api/admin/legal/sources", { data: { name: `Invented gazette ${t}`, publisher: "Imaginary Press", access_method: "manual-supplied" } })).json();
  const doc = await (await page.request.post("/api/admin/legal/documents", { data: { source_id: src.id, title: `Act text ${t}`, source_page_url: "https://example.invalid/the-act", pages: ACT } })).json();
  const ing = await page.request.post("/api/admin/legal/ingest", { data: { document_id: doc.id, instrument: { title, short_names: [`F${t}`], year: 1901 }, version_label: "original" } });
  expect(ing.ok()).toBeTruthy();
  const versionId = (await ing.json()).version_id as string;

  await page.goto("/admin");
  await page.getByTestId("admin-tab-review").click();
  await page.getByTestId("legal-review-version").selectOption(versionId);
  const sections = page.getByTestId("legal-review-section");
  await expect(sections).toHaveCount(3);
  await expect(sections.first().getByTestId("legal-review-status")).toContainText("Draft");
  await expect(sections.first().getByTestId("legal-review-source")).toHaveAttribute("href", "https://example.invalid/the-act");

  // no name yet: nothing can be approved
  await expect(sections.nth(2).getByTestId("legal-review-approve")).toBeDisabled();
  await page.getByTestId("legal-review-name").fill("Adv Test Reviewer");
  await sections.nth(2).getByTestId("legal-review-approve").click();
  await expect(sections.nth(2).getByTestId("legal-review-status")).toContainText("Reviewed");
  await expect(sections.nth(2)).toContainText("Adv Test Reviewer");

  await sections.nth(1).getByTestId("legal-review-reason").fill("The word 'unless' is missing from the loaded text.");
  await sections.nth(1).getByTestId("legal-review-reject").click();
  await expect(sections.nth(1).getByTestId("legal-review-status")).toContainText("Rejected");
  await expect(sections.nth(1)).toContainText("missing from the loaded text");

  await expect(sections.first().getByTestId("legal-review-status")).toContainText("Draft"); // the untouched one is still a draft
  await page.getByTestId("legal-review-filter").selectOption("DRAFT");
  await expect(page.getByTestId("legal-review-section")).toHaveCount(1);
});
