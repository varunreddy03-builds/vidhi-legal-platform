import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { signUp } from "./helpers";

// Accessibility sweep over EVERY screen (docs/a11y/): axe with the WCAG 2.0, 2.1 and 2.2 A and AA rules plus its best-practice rules, in the dark theme at desktop width and the light
// theme at phone width, then the open menus and dialogs. Serious and critical findings fail the test (colour contrast is judged by contrast.e2e.ts, so it is reported here but not
// counted twice). Everything found, including the moderate and minor findings, is written to docs/a11y/a11y-sweep-<date>.md. The same pages are also read the way a screen reader reads
// them (the accessibility tree) and saved as text in docs/a11y/screen-reader/.
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"];
const PUBLIC = ["/", "/login", "/login?mode=signup", "/privacy", "/terms", "/cookies", "/data-rights", "/support", "/forgot-password", "/reset-password?token=x", "/verify-email?token=x", "/accept-invite?token=x", "/consent?token=x", "/no-such-page"];
const SIGNED_IN = ["/start", "/ask", "/intelligence", "/katalyst", "/katalyst/authority", "/katalyst/dates", "/katalyst/defects", "/katalyst/oldcode", "/katalyst/deadlines", "/dashboard", "/matters", "/research", "/drafts", "/activity", "/deadlines",
  "/templates", "/portal", "/conflicts", "/lawyers", "/help", "/feedback", "/legal", "/settings", "/law", "/judgments", "/recovery", "/recovery/guide"];
const COMBOS = [{ theme: "dark", view: "desktop", width: 1280, height: 800 }, { theme: "light", view: "phone", width: 375, height: 812 }] as const;

type Finding = { screen: string; theme: string; view: string; rule: string; impact: string; help: string; targets: string[] };
const found: Finding[] = [];

async function scanScreen(page: Page, screen: string, theme: string, view: string) {
  const res = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  for (const v of res.violations) {
    // On a phone the bottom menu sits over the lowest edge of the first screen. A control there is "partly obscured" until the page is scrolled, and scroll-padding (index.css) keeps a
    // focused control clear of the menu. That is reported as a note, not a failure; every other target-size problem still fails.
    const onlyCoveredByMenu = v.id === "target-size" && v.nodes.every((n) => /partially obscured/.test(n.failureSummary ?? "") && !/insufficient size \(/.test(n.failureSummary ?? ""));
    found.push({ screen, theme, view, rule: v.id + (onlyCoveredByMenu ? " (covered by the bottom menu until scrolled)" : ""), impact: onlyCoveredByMenu ? "minor" : v.impact ?? "minor", help: v.help, targets: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) });
  }
}
const blocking = () => found.filter((f) => ["serious", "critical"].includes(f.impact) && f.rule !== "color-contrast");

function report() {
  const dir = path.resolve("../docs/a11y");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `a11y-sweep-${new Date().toISOString().slice(0, 10)}.md`);
  const all: Finding[] = [];
  const parts = path.resolve("../docs/a11y/.parts");
  for (const f of fs.existsSync(parts) ? fs.readdirSync(parts) : []) all.push(...JSON.parse(fs.readFileSync(path.join(parts, f), "utf-8")));
  const byRule = new Map<string, Finding[]>();
  for (const f of all) byRule.set(f.rule, [...(byRule.get(f.rule) ?? []), f]);
  const lines = ["# Accessibility sweep", "", `Made by \`frontend/e2e/a11y-sweep.e2e.ts\`. Rules: ${TAGS.join(", ")}. Dark theme at 1280 px and light theme at 375 px. ${all.length} findings in total (the same problem on many screens counts once per screen and view).`, "",
    "| Rule | Impact | Screens | Example element | What it means |", "|---|---|---|---|---|"];
  for (const [rule, fs2] of [...byRule].sort((a, b) => b[1].length - a[1].length)) {
    lines.push(`| ${rule} | ${fs2[0].impact} | ${[...new Set(fs2.map((f) => f.screen))].slice(0, 6).join(", ")}${new Set(fs2.map((f) => f.screen)).size > 6 ? ", ..." : ""} | \`${fs2[0].targets[0] ?? ""}\` | ${fs2[0].help} |`);
  }
  fs.writeFileSync(file, lines.join("\n") + "\n");
}

test.use({ actionTimeout: 15_000 }); // a button that never appears fails in 15 seconds, not after the whole test's time

// eslint-disable-next-line no-empty-pattern -- Playwright needs the destructuring form here, even when no fixture is used
test.afterEach(({}, info) => {
  const dir = path.resolve("../docs/a11y/.parts");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, info.title.replace(/[^a-z0-9]+/gi, "_").slice(0, 60) + ".json"), JSON.stringify(found));
  found.length = 0;
});

test.afterAll(() => report());

test("every public screen: no serious findings", async ({ page }) => {
  test.setTimeout(300_000);
  for (const c of COMBOS) {
    await page.setViewportSize({ width: c.width, height: c.height });
    await page.addInitScript((t) => localStorage.setItem("vidhi-theme", t), c.theme);
    for (const p of PUBLIC) {
      await page.goto(p);
      await page.waitForLoadState("networkidle");
      await scanScreen(page, p, c.theme, c.view);
    }
  }
  expect(blocking().map((f) => `${f.screen} ${f.view}: ${f.rule} (${f.impact}) ${f.targets[0]}`)).toEqual([]);
});

test("every signed-in screen, and the open menus and dialogs: no serious findings", async ({ page }) => {
  test.setTimeout(900_000);
  await signUp(page);
  const matter = await (await page.request.post("/api/matters", { data: { title: "Sweep matter", parties: "A v B", description: "A cheque was returned." } })).json();
  await page.request.post(`/api/matters/${matter.id}/facts`, { data: { value: "The cheque was returned on 01/06/2021.", fact_type: "NOTE" } });
  for (const c of COMBOS) {
    await page.setViewportSize({ width: c.width, height: c.height });
    await page.evaluate((t) => localStorage.setItem("vidhi-theme", t), c.theme);
    for (const p of [...SIGNED_IN, `/matters/${matter.id}`]) {
      await page.goto(p);
      await page.waitForLoadState("networkidle");
      await scanScreen(page, p.replace(matter.id, ":id"), c.theme, c.view);
    }
    // menus and dialogs, opened from the home screen
    await page.goto("/start");
    await page.waitForLoadState("networkidle");
    await page.getByTestId("account-menu").click();
    await scanScreen(page, "account menu (open)", c.theme, c.view);
    await page.getByTestId("account-language").locator("summary").click();
    await scanScreen(page, "account menu, language list (open)", c.theme, c.view);
    await page.keyboard.press("Escape");
    await page.getByTestId("open-command-palette").click();
    await scanScreen(page, "search and ask (open)", c.theme, c.view);
    await page.keyboard.press("Escape");
    if (c.view === "phone") {
      await page.getByTestId("mobile-nav-more").click();
      await scanScreen(page, "More sheet (open)", c.theme, c.view);
      await page.keyboard.press("Escape");
    }
    await page.evaluate(() => window.dispatchEvent(new Event("vidhi-open-tour"))); // the Home links that open it are hidden on a phone; More has one too (tested in the journeys)
    await page.getByTestId("guided-tour").waitFor();
    await scanScreen(page, "welcome tour (open)", c.theme, c.view);
    await page.getByTestId("tour-skip").click();
  }
  expect(blocking().map((f) => `${f.screen} ${f.view}: ${f.rule} (${f.impact}) ${f.targets[0]}`)).toEqual([]);
});

test("the operator console and each of its tabs: no serious findings", async ({ page }) => {
  test.setTimeout(300_000);
  const token = execFileSync(PY, ["-I", "../scripts/e2e_seed_admin.py"], { env: { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" }, encoding: "utf-8" }).trim();
  await page.context().addCookies([{ name: "vidhi_session", value: token, domain: "localhost", path: "/" }]);
  for (const c of COMBOS) {
    await page.setViewportSize({ width: c.width, height: c.height });
    await page.addInitScript((t) => localStorage.setItem("vidhi-theme", t), c.theme);
    await page.goto("/admin");
    await page.getByTestId("admin-console").waitFor();
    for (const tab of await page.locator('[data-testid^="admin-tab-"]').all()) {
      const id = (await tab.getAttribute("data-testid")) ?? "tab";
      await tab.click();
      await page.waitForLoadState("networkidle");
      await scanScreen(page, `/admin (${id.replace("admin-tab-", "")})`, c.theme, c.view);
    }
  }
  expect(blocking().map((f) => `${f.screen} ${f.view}: ${f.rule} (${f.impact}) ${f.targets[0]}`)).toEqual([]);
});

// ---- what a screen reader is given ----
const READ = ["/login", "/login?mode=signup", "/start", "/ask", "/intelligence", "/research", "/katalyst", "/matters", "/settings"];

test("each key screen has one main heading, the landmarks a screen reader jumps between, and names on every control; the text a screen reader reads is saved", async ({ page }) => {
  test.setTimeout(300_000);
  const dir = path.resolve("../docs/a11y/screen-reader");
  fs.mkdirSync(dir, { recursive: true });
  const problems: string[] = [];
  const check = async (route: string, signedIn: boolean) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    if (signedIn) await page.getByTestId("page-title").waitFor(); // the screen's code loads on demand: read the page only once it has drawn
    else await page.locator("h1").first().waitFor();
    const tree = await page.locator("body").ariaSnapshot();
    fs.writeFileSync(path.join(dir, route.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") + ".txt"), tree + "\n");
    const h1 = await page.locator("h1").count();
    if (h1 !== 1) problems.push(`${route}: ${h1} main headings (h1), expected 1`);
    if (signedIn) {
      for (const landmark of ["main", "navigation", "banner"]) if (!tree.includes(`- ${landmark}`)) problems.push(`${route}: no ${landmark} landmark`);
      const levels = await page.evaluate(() => [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => Number(h.tagName[1])));
      levels.reduce((prev, cur) => { if (cur > prev + 1) problems.push(`${route}: heading level jumps from h${prev} to h${cur}`); return cur; }, 0);
    }
    const unnamed = await page.evaluate(() => [...document.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea")].filter((el) => {
      const e = el as HTMLElement;
      if (e.offsetParent === null && getComputedStyle(e).position !== "fixed") return false; // not shown
      if (e.closest("[aria-hidden='true']") || e.getAttribute("tabindex") === "-1") return false; // hidden from a screen reader on purpose (a bot-trap field, a menu's hidden form value)
      const labelled = e.getAttribute("aria-label") || e.getAttribute("aria-labelledby") || e.getAttribute("title") || (e as HTMLInputElement).labels?.length || (e.textContent ?? "").trim() || e.querySelector("img[alt]:not([alt=''])") || e.getAttribute("placeholder");
      return !labelled;
    }).map((el) => el.outerHTML.replace(/\s+/g, " ").slice(0, 140)));
    for (const u of unnamed) problems.push(`${route}: control with no name: ${u}`);
  };
  for (const r of READ.slice(0, 2)) await check(r, false);
  await signUp(page);
  for (const r of READ.slice(2)) await check(r, true);
  expect(problems).toEqual([]);
});

test("the keyboard reaches the main content past the menu (skip link), and the page language is announced", async ({ page }) => {
  await signUp(page);
  await page.goto("/start");
  await page.getByTestId("page-title").waitFor();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.evaluate(() => { document.body.setAttribute("tabindex", "-1"); document.body.focus(); document.body.removeAttribute("tabindex"); }); // start at the top of the page, as a person who has just opened it
  // The skip link must be the first thing the keyboard can reach in the page (the automated browser does not hand focus to the page on a bare Tab, so the order is read from the page),
  // it must be named, and using it from the keyboard must land on the main content.
  const first = await page.evaluate(() => {
    const el = document.querySelector<HTMLElement>("a[href], button, input, select, textarea, [tabindex]:not([tabindex='-1'])");
    return el ? { href: el.getAttribute("href"), text: (el.textContent ?? "").trim() } : null;
  });
  expect(first).toEqual({ href: "#main-content", text: "Skip to content" });
  await page.locator('a[href="#main-content"]').focus();
  await page.keyboard.press("Enter");
  expect(await page.evaluate(() => document.activeElement?.id)).toBe("main-content");
});
