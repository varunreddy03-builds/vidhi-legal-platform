import { execFileSync } from "node:child_process";
import { expect, request, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// The operator's product numbers: a tool run by an ordinary user shows up as one more run, with no person in it; an ordinary user cannot open the tab or the data.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const adminToken = () => execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env, encoding: "utf-8" }).trim();
const runsOf = async (page: import("@playwright/test").Page, tool: string) => Number(await page.locator(`[data-testid="product-row"][data-tool="${tool}"] [data-testid="product-runs"]`).innerText());

test("Product tab: a run is counted, rows hold no person, an ordinary user is turned away", async ({ browser, page }) => {
  test.setTimeout(180_000);
  await signUp(page);
  expect((await page.request.get("/api/admin/product")).status()).toBeGreaterThanOrEqual(403);

  const ops = await browser.newContext();
  await ops.addCookies([{ name: "vidhi_session", value: adminToken(), domain: "localhost", path: "/" }]);
  const admin = await ops.newPage();
  await admin.goto("/admin");
  await admin.getByTestId("admin-tab-product").click();
  await expect(admin.getByTestId("admin-product")).toBeVisible();
  await expect(admin.getByTestId("product-row")).toHaveCount(10);
  const before = await runsOf(admin, "date_list");

  const marker = "PRIVATE-" + Date.now().toString(36);
  const r = await page.request.post("/api/datelists", { data: { title: marker, text: `The hearing was on 12 March 2021 for ${marker}.` } });
  expect(r.status()).toBe(200);

  await admin.reload();
  await admin.getByTestId("admin-tab-product").click();
  await expect(admin.getByTestId("admin-product")).toContainText("Counters only");
  expect(await runsOf(admin, "date_list")).toBe(before + 1);
  await expect(admin.locator('[data-testid="product-row"][data-tool="date_list"]')).toContainText(/\d+(\.\d)? s/); // an average time
  await expect(admin.locator('[data-testid="product-row"][data-tool="authority_check"]')).toContainText("reported"); // the one tool with a report button
  await expect(admin.locator('[data-testid="product-row"][data-tool="date_list"]')).toContainText("–"); // no wrong-result rate for the others
  await expect(admin.getByTestId("admin-product")).not.toContainText(marker);

  await admin.setViewportSize({ width: 375, height: 812 });
  await scan(admin, "product numbers on a phone");
  await ops.close();
  const stranger = await request.newContext({ baseURL: "http://localhost:3000" });
  expect((await stranger.get("/api/admin/product")).status()).toBeGreaterThanOrEqual(401);
  await stranger.dispose();
});
