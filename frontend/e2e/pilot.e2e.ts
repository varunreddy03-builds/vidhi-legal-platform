import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { unique } from "./helpers";

// The operator creates a pilot invitation in the Admin console; the code is shown once.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";

function operatorToken(): string {
  return execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env: { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" }, encoding: "utf-8" }).trim();
}

test("the operator invites an email address, sees the link once, and can cancel it", async ({ page }) => {
  await page.context().addCookies([{ name: "vidhi_session", value: operatorToken(), domain: "localhost", path: "/" }]);
  const email = `pilot-${unique()}@example.com`;
  await page.goto("/admin");
  await page.getByTestId("admin-tab-pilot").click();
  await expect(page.getByTestId("pilot-invites")).toContainText("OPEN to anyone"); // the e2e server runs in open mode
  await page.getByTestId("pilot-invite-email").fill(email);
  await page.getByTestId("pilot-invite-create").click();
  await expect(page.getByTestId("pilot-invite-link")).toContainText(`email=${email}`);
  await expect(page.getByTestId("pilot-invite-link")).toContainText("invite=");
  const row = page.getByTestId("pilot-invite-row").filter({ hasText: email });
  await expect(row).toContainText("open");
  await row.getByRole("button", { name: "Cancel" }).click();
  await expect(row).toContainText("revoked");
});

test("the sign-up page of an invitation link is prefilled", async ({ page }) => {
  await page.goto("/login?mode=signup&invite=CODE123&email=guest@example.com");
  await expect(page.locator("#email")).toHaveValue("guest@example.com");
});
