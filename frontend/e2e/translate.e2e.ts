import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Translate and transcribe. The browser tests run the model as an empty stub, so the reply is supplied here; the number check and the rest are tested in backend/tests/test_translate.py.

test("text is translated, the number check is shown, and the page fits a phone", async ({ page }) => {
  await signUp(page);
  await page.route("**/api/translate", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    await route.fulfill({ json: { translation: "किराया Rs 52,000 है", language: "hi", language_name: "Hindi", truncated: false, note: "Written by an AI. Have someone fluent read it before it is relied on or sent.",
      checks: { ok: false, problems: ["These numbers from the original are missing or changed: 25,000."] } } });
  });
  await page.goto("/translate");
  await expect(page.getByTestId("translate-notes")).toContainText("fluent");
  await expect(page.getByTestId("translate-run")).toBeDisabled();
  await page.getByTestId("translate-text").fill("The rent is Rs 25,000.");
  await page.getByTestId("translate-target").selectOption("hi");
  await page.getByTestId("translate-run").click();
  await expect(page.getByTestId("translate-output")).toContainText("52,000");
  await expect(page.getByTestId("translate-checks")).toContainText("25,000"); // the changed number is reported, not hidden
  await expect(page.getByTestId("translate-checks")).toContainText("fluent");
  await scan(page, "Translate page with a result");
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
