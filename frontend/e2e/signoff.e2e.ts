import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// Reviewer sign-off. An ordinary person is told the page is not for them; the operator registers a reviewer (real name and enrolment number stay on the operator's side) and records a confirmation.
// The rules (one review gate, skipped provisions, nothing private in public lists) are tested in backend/tests/test_reviewers.py.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const adminToken = () => execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env, encoding: "utf-8" }).trim();

test("an ordinary person is told the sign-off page is not for them", async ({ page }) => {
  await signUp(page);
  await page.goto("/sign-off");
  await expect(page.getByTestId("signoff-none")).toBeVisible();
  await expect(page.getByTestId("signoff-register")).toHaveCount(0);
  await scan(page, "Sign-off page for an ordinary person");
});

test("the operator registers a reviewer and sees no real name outside their own list", async ({ browser, page }) => {
  test.setTimeout(180_000);
  await signUp(page);
  const ops = await browser.newContext();
  await ops.addCookies([{ name: "vidhi_session", value: adminToken(), domain: "localhost", path: "/" }]);
  const admin = await ops.newPage();
  await admin.goto("/sign-off");
  const secret = `Invented Reviewer ${unique()}`;
  await admin.getByTestId("signoff-name").fill(secret);
  await admin.getByTestId("signoff-enrolment").fill("X/1/2000");
  await admin.getByTestId("signoff-register").click();
  await expect(admin.getByTestId("signoff-register-list")).toContainText(secret); // the operator sees it
  await expect(admin.getByTestId("signoff-register-list")).toContainText("Advocate R-");
  await expect(admin.getByTestId("signoff-submit")).toBeDisabled(); // nothing can be recorded without the statement
  await scan(admin, "Sign-off page for the operator");
  // an ordinary signed-in person never sees it, in the public list of reviewers
  const pub = await page.request.get("/api/reviewers");
  expect(pub.ok()).toBeTruthy();
  expect(await pub.text()).not.toContain(secret);
  await ops.close();
});
