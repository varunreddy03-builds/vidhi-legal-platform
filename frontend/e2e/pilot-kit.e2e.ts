import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// The pilot kit end to end: a pilot lawyer reads an Authority Check report, marks one result wrong, fills the feedback form; the operator then sees both in the Admin console.
// Runs only against a server started with AUTHORITY_CHECK_ENABLED=true.
test.skip(process.env.AUTHORITY_CHECK_ENABLED !== "true", "Authority Check is off on this server");

const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const ENV = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const DRAFT = "The accused relies on Rangappa v. Sri Mohan (2010) 11 SCC 441. The complaint is under Section 138 of the Negotiable Instruments Act, 1881.";

function operatorToken(): string {
  return execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env: ENV, encoding: "utf-8" }).trim();
}

function makePilot(orgId: string) {
  execFileSync(PY, ["-I", "-c", "import os, pymongo; d = pymongo.MongoClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]; d.organizations.update_one({'id': os.environ['ORG']}, {'$set': {'pilot': True}}); d.users.update_many({'organization_id': os.environ['ORG']}, {'$set': {'pilot': True}})"], { env: { ...ENV, ORG: orgId } });
}

test("a pilot lawyer marks a result wrong and sends the form, and the operator sees both", async ({ page, browser }) => {
  await signUp(page);
  const me = await (await page.request.get("/api/auth/me")).json();
  expect(me.pilot).toBe(false);
  await expect(page.getByTestId("pilot-banner")).toHaveCount(0); // an ordinary account has no banner
  makePilot(me.organization_id);
  await page.goto("/start");
  await expect(page.getByTestId("pilot-banner")).toContainText("sample or public drafts only"); // an invited account does
  await page.getByTestId("pilot-banner-link").click();
  await expect(page).toHaveURL(/\/feedback$/);

  // the report
  await page.goto("/katalyst/authority");
  await page.getByTestId("authority-title-input").fill("Pilot sample draft");
  await page.getByTestId("authority-text-input").fill(DRAFT);
  await page.getByTestId("authority-run").click();
  await expect(page.getByTestId("authority-report")).toBeVisible({ timeout: 45_000 }); // the first check after a server start can take several seconds
  const refs = page.getByTestId("authority-ref");
  await refs.first().click();
  await page.getByTestId("authority-flag").click();
  await expect(page.getByTestId("authority-flag-save")).toBeDisabled(); // choose what is wrong first
  await page.getByTestId("authority-flag-says_not_found_but_it_exists").check();
  await page.getByTestId("authority-flag-note").fill("This case is real: the year is right.");
  await page.getByTestId("authority-flag-save").click();
  await expect(page.getByTestId("authority-flagged")).toContainText("You marked this result as wrong or unclear");
  await expect(page.getByTestId("authority-flagged")).toContainText("the reference is real");

  // the form
  await page.goto("/feedback");
  await expect(page.getByTestId("pf-send")).toBeDisabled();
  await page.getByTestId("pf-did-yes").check();
  await page.getByTestId("pf-understood-mostly").check();
  await page.getByTestId("pf-trust-4").check();
  await page.getByTestId("pf-would-maybe").check();
  await page.getByTestId("pf-wrong").fill("The label on the first case confused me.");
  await page.getByTestId("pf-contact").check();
  await page.getByTestId("pf-send").click();
  await expect(page.getByTestId("pf-thanks")).toBeVisible();

  // the operator
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: "vidhi_session", value: operatorToken(), domain: "localhost", path: "/" }]);
  const op = await ctx.newPage();
  await op.goto("/admin");
  await op.getByTestId("admin-tab-pilot").click();
  const list = op.getByTestId("pilot-feedback-list");
  await expect(list).toBeVisible();
  const wrong = list.getByTestId("pf-wrong-row").filter({ hasText: "11 SCC 441" }).filter({ hasText: me.email });
  await expect(wrong).toContainText("The tool said: Could not check"); // the label the tool gave, as stored
  await expect(wrong).toContainText("the year is right");
  await expect(wrong).not.toContainText("accused relies"); // the draft's sentence is never copied
  await expect(list.getByTestId("pf-form-row").filter({ hasText: me.email })).toContainText("rely: 4/5");
  await ctx.close();
});
