import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Runs only against a server started with OLD_CODE_CHECK_ENABLED=true.
test.skip(process.env.OLD_CODE_CHECK_ENABLED !== "true", "The old-code checker is off on this server");

const DRAFT = "The accused is charged under Sections 302 and 34 of the Indian Penal Code. A petition under Section 482 Cr.P.C. is pending. The Evidence Act was cited. Section 138 of the Negotiable Instruments Act also applies.";

test("Old-code checker: paste a draft, read every reference with the honest 'no mapping recorded' line, download, delete", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await expect(page.getByTestId("toolkit-oldcode-state")).toHaveText(/ready/i);
  await page.getByTestId("toolkit-oldcode").locator("a").click();
  await expect(page.getByTestId("oldcode-notice")).toContainText("It does not say which code applies to a matter");

  await page.getByTestId("oldcode-title-input").fill("Bail draft");
  await page.getByTestId("oldcode-text-input").fill(DRAFT);
  await page.getByTestId("oldcode-run").click();

  await expect(page.getByTestId("oldcode-report")).toBeVisible();
  await expect(page.getByTestId("oldcode-summary")).toContainText("4 references · 3 with a section number · 0 with a reviewed mapping");
  await expect(page.getByTestId("oldcode-page-note")).toContainText("pasted text, which has no pages");
  await expect(page.getByTestId("oldcode-kept")).toContainText(/Kept until 20\d\d-\d\d-\d\d, then deleted automatically/); // reports expire on their own
  await expect(page.getByTestId("oldcode-item")).toHaveCount(4); // the Negotiable Instruments Act is not one of the older criminal codes
  await expect(page.getByTestId("oldcode-item-label")).toHaveText(["Indian Penal Code · section 302", "Indian Penal Code · section 34", "Code of Criminal Procedure · section 482", "Indian Evidence Act · named"]);
  await expect(page.getByTestId("oldcode-item-mapping").first()).toContainText("No verified mapping is recorded for this provision. That does not mean none exists");
  await expect(page.getByTestId("oldcode-item-note").last()).toContainText("without a section number");
  await expect(page.getByTestId("oldcode-caveat")).toContainText("has not decided which text applies");
  await expect(page.getByText(/\boutdated\b|\brepealed\b|use section/i)).toHaveCount(0);

  const [download] = await Promise.all([page.waitForEvent("popup").catch(() => null), page.getByTestId("oldcode-export-docx").click()]);
  void download; // the file itself is checked by the backend tests

  await page.reload(); // saved on the server
  await expect(page.getByTestId("oldcode-item")).toHaveCount(4);
  await page.getByTestId("oldcode-delete").click();
  await expect(page.getByTestId("oldcode-list")).toBeVisible();
  await expect(page.getByTestId("oldcode-row")).toHaveCount(0);
});

test("Old-code checker: a draft with none says that is not a finding there are none; a phone does not scroll sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/katalyst/oldcode");
  await page.getByTestId("oldcode-text-input").fill("The parties signed a lease. Nothing else is stated.");
  await page.getByTestId("oldcode-run").click();
  await expect(page.getByTestId("oldcode-summary")).toContainText("That is not a finding that the draft has none.");
  await page.goto("/katalyst/oldcode");
  await page.getByTestId("oldcode-text-input").fill("Charged under Sections 323, 324, 325, 326, 498-A, 304-B and 34 of the Indian Penal Code, 1860, read with Section 482(1) of the Code of Criminal Procedure, 1973.");
  await page.getByTestId("oldcode-run").click();
  await expect(page.getByTestId("oldcode-item")).toHaveCount(8);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
