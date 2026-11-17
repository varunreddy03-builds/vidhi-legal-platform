import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers";

// Opens every screen a signed-in person can reach and fails on a crash, a console error or a failing server call.
// It proves that each screen draws and talks to the server without errors. It does NOT prove that the AI answers are good: the AI keys are not set on the test server.
const SCREENS = [
  "/start", "/intelligence", "/ask", "/research", "/matters", "/drafts", "/templates", "/deadlines", "/dashboard", "/activity", "/conflicts", "/lawyers", "/legal",
  "/katalyst", "/katalyst/authority", "/katalyst/dates", "/katalyst/defects", "/katalyst/oldcode", "/katalyst/deadlines",
  "/recovery", "/recovery/guide", "/settings", "/help", "/support", "/privacy", "/terms", "/cookies", "/data-rights",
];

// A server error that is expected on a fresh account is listed here with the reason; anything else fails the test.
const EXPECTED: { url: RegExp; status: number; why: string }[] = [];

async function visit(page: Page, path: string, problems: string[]) {
  const seen: string[] = [];
  const onConsole = (m: { type(): string; text(): string }) => {
    if (m.type() === "error" && !/favicon|Failed to load resource: the server responded with a status of 4\d\d/.test(m.text())) seen.push(`console: ${m.text().slice(0, 160)}`);
  };
  const onError = (e: Error) => seen.push(`page error: ${e.message.slice(0, 160)}`);
  const onResponse = (r: { status(): number; url(): string }) => {
    const u = r.url();
    if (u.includes("/api/") && r.status() >= 500 && !EXPECTED.some((x) => x.url.test(u) && x.status === r.status())) seen.push(`${r.status()} ${u.replace(/^https?:\/\/[^/]+/, "")}`);
  };
  page.on("console", onConsole);
  page.on("pageerror", onError);
  page.on("response", onResponse);
  await page.goto(path);
  await page.waitForLoadState("networkidle");
  const mainArea = page.locator("main#main-content, main").first();
  await mainArea.waitFor({ state: "visible", timeout: 15_000 }).catch(() => {}); // a cold dev server can still be drawing the screen when the network goes quiet; a screen that never draws still fails below
  const main = await mainArea.isVisible().catch(() => false);
  if (!main) seen.push("no main area drawn");
  const text = (await page.locator("body").innerText()).trim();
  if (text.length < 40) seen.push("screen is nearly empty");
  if (/something went wrong|unexpected error|undefined|\[object Object\]/i.test(text)) seen.push("screen shows an error or raw text");
  page.off("console", onConsole);
  page.off("pageerror", onError);
  page.off("response", onResponse);
  for (const s of seen) problems.push(`${path}: ${s}`);
}

test("every screen opens without a crash, a console error or a server error", async ({ page }) => {
  test.setTimeout(420_000); // 28 page loads
  await signUp(page);
  const problems: string[] = [];
  for (const path of SCREENS) await visit(page, path, problems);
  expect(problems, problems.join("\n")).toEqual([]);
});

test("the old addresses still work: /toolkit forwards to /katalyst and the removed pages do not crash", async ({ page }) => {
  await signUp(page);
  await page.goto("/toolkit/dates");
  await expect(page).toHaveURL(/\/katalyst\/dates$/);
  await page.goto("/this-page-does-not-exist");
  await expect(page.locator("body")).toContainText(/not found|can.t find|404|does not exist/i);
});
