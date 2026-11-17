import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Colour contrast, enforced, in both themes and at phone width (the general sweep in accessibility.e2e.ts reports contrast but does not fail on it).
// Animations are switched off so the glass background is still while the colours are measured.
const ROUTES = ["/login", "/start", "/intelligence", "/ask", "/research", "/katalyst", "/matters", "/deadlines", "/settings", "/legal", "/help"];
const VIEWS = [
  { theme: "light", width: 375, height: 812 },
  { theme: "dark", width: 375, height: 812 },
  { theme: "light", width: 1280, height: 800 },
  { theme: "dark", width: 1280, height: 800 },
];

test("text has enough colour contrast in the light and dark themes, on a phone and a laptop", async ({ page }) => {
  test.setTimeout(300_000);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await signUp(page);
  const problems: string[] = [];
  for (const v of VIEWS) {
    await page.setViewportSize({ width: v.width, height: v.height });
    await page.evaluate((t) => localStorage.setItem("vidhi-theme", t), v.theme);
    for (const route of ROUTES) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");
      const result = await new AxeBuilder({ page }).withRules(["color-contrast"]).analyze();
      for (const viol of result.violations) {
        for (const n of viol.nodes.slice(0, 3)) problems.push(`${route} ${v.theme} ${v.width}px: ${n.target.join(" ")} ${n.any[0]?.message ?? ""}`.slice(0, 260));
      }
    }
  }
  expect(problems, problems.join("\n")).toEqual([]);
});
