import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Phone quality, measured on a 375 x 812 screen: the page can be zoomed, it can be installed, inputs do not make an iPhone zoom in, and nothing to tap is too small.
const ROUTES = ["/start", "/katalyst", "/katalyst/authority", "/katalyst/dates", "/katalyst/defects", "/katalyst/oldcode", "/matters", "/deadlines", "/recovery", "/settings"];
const MIN_TAP = 24; // WCAG 2.2 level AA "target size (minimum)"; 44 is the Apple guideline, reported but not required here

test("phone: the page can be zoomed and installed, and the install files are complete", async ({ page, request }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/login");
  const viewport = await page.locator('meta[name="viewport"]').getAttribute("content");
  expect(viewport).toContain("width=device-width");
  expect(viewport ?? "").not.toMatch(/user-scalable\s*=\s*(no|0)|maximum-scale\s*=\s*1(\.0)?\b/); // people must be able to zoom
  expect(await page.locator('meta[name="theme-color"]').count()).toBeGreaterThan(0);
  expect(await page.locator('link[rel="apple-touch-icon"]').count()).toBeGreaterThan(0);
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBeTruthy();
  const res = await request.get(new URL(href!, page.url()).toString());
  expect(res.ok()).toBe(true);
  const m = await res.json();
  expect(m.name).toBeTruthy();
  expect(m.start_url).toBeTruthy();
  expect(["standalone", "fullscreen", "minimal-ui"]).toContain(m.display);
  const sizes = (m.icons ?? []).map((i: { sizes: string }) => i.sizes);
  expect(sizes.join(" ")).toContain("192x192");
  expect(sizes.join(" ")).toContain("512x512");
});

test("phone: on the main screens nothing to tap is smaller than 24px and no text box makes an iPhone zoom in", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  const problems: string[] = [];
  const below44: string[] = [];
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("main#main-content")).toBeVisible();
    await page.waitForLoadState("networkidle");
    const found = await page.evaluate((min) => {
      const out = { small: [] as string[], medium: [] as string[], zoom: [] as string[] };
      const label = (el: Element) => `${el.tagName.toLowerCase()}${el.getAttribute("data-testid") ? `[${el.getAttribute("data-testid")}]` : ""} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 24)}"`;
      for (const el of Array.from(document.querySelectorAll("a[href], button, select, input:not([type=hidden]), textarea, [role=button], [role=tab]"))) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (r.width === 0 || r.height === 0 || cs.visibility === "hidden" || cs.display === "none") continue;
        if (r.bottom < 0 || r.right < 0) continue;
        if (el.id === "skip-to-content" || el.getAttribute("data-testid") === "skip-to-content") continue; // a skip link is hidden until the keyboard focuses it
        if (el.tagName === "A" && el.querySelector("button")) continue; // the button inside is the tap target
        const isTick = el.tagName === "INPUT" && ["checkbox", "radio"].includes((el as HTMLInputElement).type);
        const box = isTick ? (el.closest("label") ?? (el.id ? document.querySelector(`label[for="${el.id}"]`) : null) ?? el).getBoundingClientRect() : r; // a tick box is tapped through its label
        const inline = el.tagName === "A" && cs.display === "inline" && !!el.closest("p, li, span, div") && (el.textContent || "").trim().split(/\s+/).length > 3; // a link inside a sentence is exempt (WCAG)
        if (!inline && (box.width < min || box.height < min)) out.small.push(`${label(el)} ${Math.round(box.width)}x${Math.round(box.height)}`);
        else if (!inline && box.height < 44) out.medium.push(label(el));
        if (["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName) && !["checkbox", "radio", "file", "submit", "button", "range"].includes((el as HTMLInputElement).type) && parseFloat(cs.fontSize) < 16) out.zoom.push(`${label(el)} ${cs.fontSize}`);
      }
      return out;
    }, MIN_TAP);
    for (const s of found.small) problems.push(`${route}: too small to tap: ${s}`);
    for (const z of found.zoom) problems.push(`${route}: text under 16px (iPhone zooms in): ${z}`);
    for (const s of found.medium) below44.push(`${route}: ${s}`);
  }
  console.log(`BELOW-44 (${below44.length}):\n${below44.slice(0, 40).join("\n")}`);
  console.log(`PROBLEMS (${problems.length}):\n${problems.join("\n")}`);
  expect(problems).toEqual([]);
});
