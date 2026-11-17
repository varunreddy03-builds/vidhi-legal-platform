import { test } from "@playwright/test";
import { scan, signUp } from "./helpers";

const PUBLIC = ["/login", "/login?mode=signup", "/privacy", "/terms", "/cookies", "/data-rights", "/support", "/forgot-password"];
const SIGNED_IN = ["/start", "/recovery/guide", "/intelligence", "/ask", "/research", "/katalyst", "/dashboard", "/matters", "/drafts", "/templates", "/deadlines", "/conflicts", "/legal", "/help", "/settings", "/recovery", "/support"];

test("public pages have no serious accessibility problems", async ({ page }) => {
  for (const path of PUBLIC) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await scan(page, path);
  }
});

test("signed-in pages have no serious accessibility problems", async ({ page }) => {
  test.setTimeout(240_000); // about 16 pages, each loaded and scanned; one minute was too close to the limit
  await signUp(page);
  for (const path of SIGNED_IN) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await scan(page, path);
  }
});