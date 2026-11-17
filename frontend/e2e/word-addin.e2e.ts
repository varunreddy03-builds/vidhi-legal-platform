import { expect, test } from "@playwright/test";
import { scan } from "./helpers";

// The Word task pane page (src/addin/TaskPane.tsx). Opened in a normal browser it is not inside Word, so it must say so plainly instead of showing a broken screen.
// The Word-side behaviour (reading paragraphs, selecting a range, tracked replacement, comments) needs Word itself and is not covered here: see addins/README.md for the manual check.
test("the Word add-in page says it works inside Word when opened in a browser, and is accessible", async ({ page }) => {
  await page.route("https://appsforoffice.microsoft.com/**", (route) => route.abort()); // never reach the real Office.js server from a test
  await page.goto("/addin/word");
  await expect(page.getByRole("alert")).toContainText("This panel works inside Microsoft Word", { timeout: 20_000 });
  await scan(page, "Word add-in page outside Word");
});
