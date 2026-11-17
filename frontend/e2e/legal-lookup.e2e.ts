import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

test("the legal lookup page always says its text is not verified and handles a search that finds nothing", async ({ page }) => {
  await signUp(page);
  await page.goto("/legal");
  await expect(page.getByTestId("legal-page")).toContainText("not verified as law");
  await expect(page.getByTestId("legal-page")).toContainText("They do not mean the platform covers every Act");
  await page.getByTestId("legal-query").fill("Section 9999 of the Nonexistent Imaginary Act");
  await page.getByTestId("legal-search").click();
  await expect(page.getByTestId("legal-results")).toContainText("Nothing matched");
  await expect(page.getByTestId("legal-results")).toContainText("does not mean no such provision exists");
  await scan(page, "legal lookup with a result");
});