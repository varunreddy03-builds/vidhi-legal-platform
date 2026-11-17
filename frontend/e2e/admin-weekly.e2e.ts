import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { unique } from "./helpers";

// The operator's weekly view (Admin console > This week). The operator account is seeded straight into the test database; invented usage rows are added for the screenshots and removed after.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const run = (script: string, ...args: string[]) => execFileSync(PY, ["-I", script, ...args], { env, encoding: "utf-8" }).trim();
const shots = path.resolve("../docs/operator");

test("This week shows AI cost by day, errors, wrong-result reports, library review progress and pilot accounts; screenshots in both themes and sizes", async ({ page }) => {
  test.setTimeout(180_000);
  const tag = unique();
  run("../scripts/e2e_seed_weekly.py", tag);
  try {
    await page.context().addCookies([{ name: "vidhi_session", value: run("../scripts/e2e_seed_admin.py"), domain: "localhost", path: "/" }]);
    fs.mkdirSync(shots, { recursive: true });
    for (const [theme, view, width, height] of [["dark", "desktop", 1280, 900], ["light", "phone", 375, 812]] as const) {
      await page.setViewportSize({ width, height });
      await page.addInitScript((t) => localStorage.setItem("vidhi-theme", t), theme);
      await page.goto("/admin");
      await page.getByTestId("admin-tab-weekly").click();
      await expect(page.getByTestId("admin-weekly")).toBeVisible();
      // the five blocks the owner reads each week
      for (const id of ["cost", "errors", "wrong", "library", "pilot"]) await expect(page.getByTestId(`weekly-${id}`)).toBeVisible();
      await expect(page.getByTestId("weekly-cost-row")).toHaveCount(14); // a quiet day is a row too
      await expect(page.getByTestId("weekly-error-rate")).toContainText(/\d+ of \d+ calls failed \(\d+(\.\d)?%\)/);
      await expect(page.getByTestId("weekly-wrong-counts")).toContainText(/Answers marked down: \d+ .*Katalyst results marked wrong: \d+/);
      await expect(page.getByTestId("weekly-library-counts")).toContainText(/of \d+ sections reviewed/);
      await expect(page.getByRole("progressbar", { name: "Share of sections reviewed" })).toBeVisible();
      await expect(page.getByTestId("weekly-pilot-row").filter({ hasText: "Demo Pilot Chambers" })).toHaveCount(1);
      // nothing from a matter or a comment is on the screen
      await expect(page.getByText("Demo matter")).toHaveCount(0);
      // no sideways scrolling of the page itself
      expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
      await page.screenshot({ path: path.join(shots, `weekly-${view}-${theme}.png`), fullPage: true });
    }
  } finally {
    run("../scripts/e2e_seed_weekly.py", tag, "--clean");
  }
});
