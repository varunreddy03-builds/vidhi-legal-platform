import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Runs only against a server started with DEFECT_CHECK_ENABLED=true.
test.skip(process.env.DEFECT_CHECK_ENABLED !== "true", "The pre-filing defect check is off on this server");

const DRAFT = "1. The petitioner, _______, resides at Pune.\n2. The respondent replied.\n4. The matter was heard, see Annexure P-1 and Annexure P-3.\nAs stated in paragraph 9, the the facts are clear.";

test("Pre-filing defect check: paste a draft, read the slips with honest notes, download, delete", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await expect(page.getByTestId("toolkit-defects-state")).toHaveText(/ready/i);
  await page.getByTestId("toolkit-defects").locator("a").click();
  await expect(page.getByTestId("defect-notice")).toContainText("does not know any court");
  await expect(page.getByTestId("defect-notice")).toContainText("does not say a draft is defective");

  await page.getByTestId("defect-title-input").fill("Reply draft");
  await page.getByTestId("defect-text-input").fill(DRAFT);
  await page.getByTestId("defect-run").click();

  await expect(page.getByTestId("defect-report")).toBeVisible();
  await expect(page.getByTestId("defect-summary")).toContainText("5 places to look at");
  await expect(page.getByTestId("defect-page-note")).toContainText("pasted text, which has no pages");
  await expect(page.getByTestId("defect-kept")).toContainText(/Kept until 20\d\d-\d\d-\d\d, then deleted automatically/); // reports expire on their own
  const items = page.getByTestId("defect-item");
  await expect(items).toHaveCount(5);
  await expect(page.getByTestId("defect-item-raw").first()).toHaveText("_______");
  await expect(page.getByTestId("defect-item-note").first()).toContainText("meant to be filled by hand"); // every note says why it may not be a slip
  await expect(page.getByText(/\blied\b|will be rejected/i)).toHaveCount(0);

  const [download] = await Promise.all([page.waitForEvent("popup").catch(() => null), page.getByTestId("defect-export-docx").click()]);
  void download; // the file itself is checked by the backend tests

  await page.reload(); // saved on the server
  await expect(page.getByTestId("defect-item")).toHaveCount(5);
  await page.getByTestId("defect-delete").click();
  await expect(page.getByTestId("defect-list")).toBeVisible();
  await expect(page.getByTestId("defect-row")).toHaveCount(0);
});

test("Pre-filing defect check: a clean draft says nothing was pointed out and that this is not a finding it is ready; a PDF gets real pages; a phone does not scroll sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/katalyst/defects");
  await page.getByTestId("defect-text-input").fill("1. The petitioner filed the suit.\n2. The respondent replied.\n3. The matter was heard.");
  await page.getByTestId("defect-run").click();
  await expect(page.getByTestId("defect-summary")).toContainText("Nothing was pointed out. That is not a finding that the draft is ready to file.");
  await page.goto("/katalyst/defects");
  await page.getByTestId("defect-file-input").setInputFiles(fileURLToPath(new URL("./fixtures/blank-on-page-2.pdf", import.meta.url)));
  await expect(page.getByTestId("defect-report")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("defect-page-note")).toContainText("Page numbers are the pages of the PDF file");
  await expect(page.getByTestId("defect-item")).toHaveCount(1);
  await expect(page.getByTestId("defect-item-where")).toHaveText("page 2");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
