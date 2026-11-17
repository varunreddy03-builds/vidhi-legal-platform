import { execFileSync } from "node:child_process";
import { expect, request, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Settings shows the plans from the plans file (prices not set show as such), the organisation's usage, and what changes when the operator puts the organisation on the Firm plan by hand. Phone and laptop.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const adminToken = () => execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env, encoding: "utf-8" }).trim();

test("Settings shows the plans, the usage, and the Firm plan once the operator sets it; no checkout for Firm", async ({ page, baseURL }) => {
  await signUp(page);
  await page.goto("/settings");
  const plan = page.getByTestId("settings-plan");
  await expect(plan).toBeVisible();
  await expect(page.getByTestId("plan-usage")).toContainText(/Today: \d+ of 5 AI requests used by your organisation\. People: 1 \(no limit on your plan\)/);
  await expect(page.getByTestId("plan-firm-card")).toContainText("Price to be announced");
  await expect(page.getByTestId("plan-firm-card")).toContainText("Up to 25 people");
  await expect(page.getByTestId("plan-firm-card")).toContainText("no online checkout");

  // the operator puts this organisation on the Firm plan
  const me = await (await page.request.get("/api/auth/me")).json();
  const ops = await request.newContext({ baseURL, extraHTTPHeaders: { Cookie: `vidhi_session=${adminToken()}` } });
  const seen = await ops.get("/api/admin/plans");
  expect(seen.status()).toBe(200);
  expect((await seen.json()).file.problem).toBeNull();
  const done = await ops.post(`/api/admin/organisations/${me.organization_id}/plan`, { data: { plan: "FIRM", months: 12 } });
  expect(done.status()).toBe(200);

  await page.reload();
  await expect(page.getByTestId("settings-plan-badge")).toHaveText("FIRM");
  await expect(page.getByTestId("plan-firm-note")).toContainText("Firm plan, set up by VIDHI until");
  await expect(page.getByTestId("plan-usage")).toContainText("of 2000 AI requests used by your organisation. People: 1 of 25 allowed");
  await expect(page.locator('[data-testid^="settings-upgrade-"]')).toHaveCount(0); // a paid plan is not offered an upgrade
  await expect(page.getByTestId("cancel-subscription")).toHaveCount(0);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await scan(page, "settings plan section on a phone");
  await ops.dispose();
});
