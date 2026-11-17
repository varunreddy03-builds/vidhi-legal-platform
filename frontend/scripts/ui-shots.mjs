// Before / after screenshots of the main screens: desktop 1280x800 and phone 375x812, dark and light.
//   node scripts/ui-shots.mjs <set-name> [base-url]     e.g. node scripts/ui-shots.mjs before http://localhost:3010
// Writes ../docs/redesign/slice2/<set-name>/<screen>-<desktop|phone>-<dark|light>.png. Uses the Edge or Chrome already installed (PW_CHANNEL, default msedge).
// Signs up a throwaway account in whatever backend the base URL proxies to (use a throwaway database).
import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const set = process.argv[2] || "shots";
const base = process.argv[3] || "http://localhost:3010";
const out = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../docs/redesign/slice2", set);
fs.mkdirSync(out, { recursive: true });

const SCREENS = [["start", "/start"], ["intelligence", "/intelligence"], ["ask", "/ask"], ["research", "/research"], ["katalyst", "/katalyst"], ["settings", "/settings"]];
const VIEWS = { desktop: { width: 1280, height: 800 }, phone: { width: 375, height: 812 } };
const id = Date.now().toString(36);

const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || "msedge" });
for (const theme of ["dark", "light"]) {
  for (const [vname, size] of Object.entries(VIEWS)) {
    const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: 1, isMobile: vname === "phone", hasTouch: vname === "phone" });
    await ctx.addInitScript((t) => { try { localStorage.setItem("vidhi-theme", t); } catch { /* none */ } }, theme);
    const page = await ctx.newPage();
    await page.goto(base + "/login?mode=signup");
    await page.getByTestId("auth-fullname-input").fill("Shots Lawyer");
    await page.getByTestId("auth-org-input").fill(`Shots Chambers ${id}${theme}${vname}`);
    await page.getByTestId("auth-email-input").fill(`shots-${id}-${theme}-${vname}@example.com`);
    await page.getByTestId("auth-password-input").fill(`Shots-${id}-Aa1`);
    await page.getByTestId("auth-privacy-checkbox").check();
    await page.waitForTimeout(1600);
    await page.getByTestId("auth-submit-button").click();
    await page.getByTestId("start-greeting").waitFor({ timeout: 20000 });
    for (const [name, route] of SCREENS) {
      await page.goto(base + route);
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await page.waitForTimeout(600);
      await page.screenshot({ path: path.join(out, `${name}-${vname}-${theme}.png`), fullPage: false });
    }
    // the account menu, open (it exists only after slice 2: skipped when the page has no such button)
    await page.goto(base + "/start");
    await page.waitForLoadState("networkidle").catch(() => undefined);
    const menu = page.getByTestId("account-menu");
    if (await menu.count()) {
      await menu.click();
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(out, `account-menu-${vname}-${theme}.png`), fullPage: false });
    }
    await ctx.close();
  }
}
await browser.close();
console.log("saved to", out, fs.readdirSync(out).length, "files");

