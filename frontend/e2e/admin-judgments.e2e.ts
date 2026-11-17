import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { scan } from "./helpers";

// Admin console > Judgment links, opened as the operator (seeded straight into the test database by scripts/e2e_seed_admin.py): the panel loads, says plainly that
// a name is needed before anything can be approved, and has no serious accessibility problem.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";

function operatorToken(): string {
  return execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env: { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" }, encoding: "utf8" }).trim();
}

test("the Admin judgment-links tab opens for the operator, asks for a full name, and is accessible", async ({ page }) => {
  await page.context().addCookies([{ name: "vidhi_session", value: operatorToken(), domain: "localhost", path: "/" }]);
  await page.goto("/admin");
  await page.getByTestId("admin-tab-judgments").click();
  const panel = page.getByTestId("judgment-links");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Enter your full name above to approve or reject.");
  await expect(panel.getByText(/link\(s\) in this list/)).toBeVisible();
  await page.getByTestId("judgment-links-name").fill("Adv Test Reviewer");
  await expect(panel).not.toContainText("Enter your full name above to approve or reject.");
  await page.getByLabel("Show").selectOption("REVIEWED");
  await expect(panel.getByText(/link\(s\) in this list/)).toBeVisible();
  await scan(page, "/admin (judgment links)");
});
