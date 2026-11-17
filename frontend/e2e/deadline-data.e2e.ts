import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";
import { scan, unique } from "./helpers";

// The operator loads a holiday calendar from a file, has a named advocate mark it reviewed, switches the court on, sees "X of Y courts", and rolls the load back. Everything in the file is invented.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const run = (script: string, ...args: string[]) => execFileSync(PY, ["-I", script, ...args], { env, encoding: "utf-8" }).trim();

test("load a calendar file, review it under a name, switch the court on, then roll the load back", async ({ page }) => {
  test.setTimeout(180_000);
  const tag = unique().replace(/[^a-z0-9]/gi, "").slice(0, 10);
  const court = run("../scripts/e2e_seed_court.py", tag);
  await page.context().addCookies([{ name: "vidhi_session", value: run("../scripts/e2e_seed_admin.py"), domain: "localhost", path: "/" }]);
  await page.goto("/admin");
  await page.getByTestId("admin-tab-deadlines").click();
  await expect(page.getByTestId("admin-deadlines")).toBeVisible();
  await expect(page.getByTestId("deadline-summary")).toContainText(/of \d+ courts/); // wait for the list to arrive
  const total = (await page.getByTestId("deadline-summary").innerText()).match(/of (\d+) courts/)![1];
  const live = Number((await page.getByTestId("deadline-summary").innerText()).match(/for (\d+) of/)![1]);

  const good = { kind: "court_calendar", court, year: 2031, source_url: "https://example.invalid/official/holidays", source_checked_on: "2026-11-01", weekend_days: [5, 6], holidays: [{ date: "2031-01-14", name: "Invented Day" }] };
  const file = (data: unknown) => ({ name: `${tag}.json`, mimeType: "application/json", buffer: Buffer.from(JSON.stringify(data)) });

  // a file without its source is refused in words, and nothing is stored
  await page.getByTestId("deadline-file").setInputFiles(file({ ...good, source_url: undefined }));
  await page.getByTestId("deadline-load").click();
  await expect(page.getByTestId("deadline-problem")).toContainText("official source");

  await page.getByTestId("deadline-file").setInputFiles(file(good));
  await page.getByTestId("deadline-preview").click();
  await expect(page.getByTestId("deadline-result")).toContainText("Checked, nothing stored");
  await page.getByTestId("deadline-load").click();
  await expect(page.getByTestId("deadline-result")).toContainText("Loaded: 1 calendar");
  const card = page.getByTestId("deadline-court").filter({ hasText: court });
  await expect(card).toContainText("not reviewed");
  await expect(card).toContainText("Source: https://example.invalid/official/holidays (checked 2026-11-01)");
  await expect(card.getByTestId("deadline-enable")).toHaveCount(0); // no switch before a review
  await expect(card.getByTestId("deadline-review")).toBeDisabled(); // and no review without the advocate's name

  await page.getByTestId("deadline-reviewer").fill("Adv Invented Reviewer");
  await page.getByTestId("deadline-on").fill("2026-10-20");
  await card.getByTestId("deadline-review").click();
  await expect(card).toContainText("reviewed by Adv Invented Reviewer on 2026-10-20");
  await expect(page.getByTestId("deadline-summary")).toContainText(`for ${live} of ${total} courts`); // reviewed but not switched on: not counted
  await card.getByTestId("deadline-enable").click();
  await expect(card).toContainText("switched on");
  await expect(page.getByTestId("deadline-summary")).toContainText(`for ${live + 1} of ${total} courts`);
  await scan(page, "deadline data screen");

  await card.getByTestId("deadline-rollback").click();
  await expect(card).toContainText("not reviewed");
  await expect(card).toContainText("switched off");
  await expect(page.getByTestId("deadline-summary")).toContainText(`for ${live} of ${total} courts`);

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
