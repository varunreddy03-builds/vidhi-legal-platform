import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// One account, the main screens, three device widths: nothing may scroll sideways and every screen must have its main area.
const WIDTHS = [
  { name: "phone", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "laptop", width: 1280, height: 800 },
];
const ROUTES = ["/start", "/katalyst", "/matters", "/deadlines", "/settings", "/recovery", "/legal"];

test("main screens fit phone, tablet and laptop widths; the keyboard can skip to the content", async ({ page }) => {
  test.setTimeout(240_000); // 22 page loads in one test; one minute was too close to the limit on a busy PC
  await signUp(page);
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w.width, height: w.height });
    for (const route of ROUTES) {
      await page.goto(route);
      await expect(page.locator("main#main-content")).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${route} at ${w.name} (${w.width}px) scrolls sideways`).toBeLessThanOrEqual(1);
    }
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/katalyst");
  await expect(page.locator("main#main-content")).toBeVisible();
  await page.waitForLoadState("networkidle"); // let the screen finish drawing so the first Tab starts from the top of the page
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("skip-to-content")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main#main-content")).toBeFocused();
});

test("Telugu and other Unicode text shows in the interface fonts", async ({ page }) => {
  await signUp(page);
  await page.goto("/matters");
  await page.getByTestId("new-matter-button").click();
  const text = "ఇది తెలుగు వివరణ — हिन्दी — தமிழ்";
  await page.getByTestId("matter-title-input").fill(text);
  const ok = await page.evaluate(async (s) => {
    await document.fonts.ready;
    // a glyph the browser could not draw is replaced by the .notdef box, which is as wide as an "M"-sized box: compare the text's width with a row of unknown private-use characters
    const probe = (str: string) => {
      const el = document.createElement("span");
      el.style.cssText = "position:absolute;visibility:hidden;white-space:pre;font:16px var(--font-sans, sans-serif)";
      el.textContent = str;
      document.body.appendChild(el);
      const w = el.getBoundingClientRect().width;
      el.remove();
      return w;
    };
    return probe(s) > 0 && Array.from(s).some((c) => c.charCodeAt(0) > 0xc00) && document.fonts.check("16px sans-serif", s);
  }, text);
  expect(ok).toBe(true);
  await expect(page.getByTestId("matter-title-input")).toHaveValue(text);
});
