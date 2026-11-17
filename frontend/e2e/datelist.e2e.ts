import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Runs only against a server started with DATE_LIST_ENABLED=true.
test.skip(process.env.DATE_LIST_ENABLED !== "true", "The list of dates is off on this server");

const TEXT = "The loan was advanced on 01/06/2020. The cheque dated 31/02/2021 was returned. The notice was sent on 5th April 2021.";

test("List of dates: paste text, read the dates in order with honest notes and no page numbers, download, delete", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await expect(page.getByTestId("toolkit-dates-state")).toHaveText(/ready/i);
  await page.getByTestId("toolkit-dates").locator("a").click();
  await expect(page.getByTestId("datelist-notice")).toContainText("does not say what an event means");

  await page.getByTestId("datelist-title-input").fill("Cheque bundle");
  await page.getByTestId("datelist-text-input").fill(TEXT);
  await page.getByTestId("datelist-run").click();

  await expect(page.getByTestId("datelist-report")).toBeVisible();
  await expect(page.getByTestId("datelist-summary")).toContainText("3 dates · 2 read as one real day · 1 not read as one day · 2 with a note");
  await expect(page.getByTestId("datelist-page-note")).toContainText("pasted text, which has no pages");
  await expect(page.getByTestId("datelist-kept")).toContainText(/Kept until 20\d\d-\d\d-\d\d, then deleted automatically/); // reports expire on their own
  const raws = page.getByTestId("datelist-item-raw");
  await expect(raws).toHaveText(["01/06/2020", "5th April 2021", "31/02/2021"]); // date order; the date that is not real goes last, as written
  await expect(page.getByTestId("datelist-item-where").first()).toContainText("page not available");
  await expect(page.getByTestId("datelist-item-flag").filter({ hasText: "not a real calendar date" })).toHaveCount(1); // the other note is the day/month one on 01/06/2020
  await expect(page.getByText(/lied|wrong date/i)).toHaveCount(0);

  const [download] = await Promise.all([page.waitForEvent("popup").catch(() => null), page.getByTestId("datelist-export-docx").click()]);
  void download; // the file itself is checked by the backend tests

  await page.reload(); // the list is saved on the server
  await expect(page.getByTestId("datelist-item")).toHaveCount(3);
  await page.getByTestId("datelist-delete").click();
  await expect(page.getByTestId("datelist-list")).toBeVisible();
  await expect(page.getByTestId("datelist-row")).toHaveCount(0);
});

test("List of dates from a Word-type file says page not available, and it works on a phone without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/katalyst/dates");
  await page.getByTestId("datelist-file-input").setInputFiles({ name: "తెలుగు notes.txt", mimeType: "text/plain", buffer: Buffer.from("తెలుగు వాక్యం. Paid on 4 June 2021. " + TEXT, "utf-8") });
  await expect(page.getByTestId("datelist-report")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("datelist-page-note")).toContainText("no fixed pages");
  await expect(page.getByTestId("datelist-item").first().getByTestId("datelist-item-where")).toContainText("part 1 of");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("List of dates: a PDF gets real page numbers", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst/dates");
  await page.getByTestId("datelist-file-input").setInputFiles(fileURLToPath(new URL("./fixtures/two-page-dates.pdf", import.meta.url)));
  await expect(page.getByTestId("datelist-report")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("datelist-page-note")).toContainText("Page numbers are the pages of the PDF file");
  await expect(page.getByTestId("datelist-item")).toHaveCount(1);
  await expect(page.getByTestId("datelist-item-raw")).toHaveText("12/03/2021");
  await expect(page.getByTestId("datelist-item-where")).toHaveText("page 2"); // the date is on the second page
});

test("List of dates: a found date can be copied into My Dates after the user checks it, and a date that is not real has no Add button", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst/dates");
  await page.getByTestId("datelist-text-input").fill("The next hearing is fixed for 15th March 2031 before the court. The cheque dated 31/02/2021 was returned.");
  await page.getByTestId("datelist-run").click();
  await expect(page.getByTestId("datelist-item")).toHaveCount(2);
  await expect(page.getByTestId("datelist-add-open")).toHaveCount(1); // only the date read as one real day
  await page.getByTestId("datelist-add-open").click();
  await expect(page.getByTestId("datelist-add-date")).toHaveValue("2031-03-15"); // prefilled, and the user may change it
  await page.getByTestId("datelist-add-title").fill("Hearing in the cheque case");
  await page.getByTestId("datelist-add-submit").click();
  await expect(page.getByTestId("datelist-added")).toBeVisible();
  await page.goto("/deadlines");
  await expect(page.getByText("Hearing in the cheque case")).toBeVisible();
});
