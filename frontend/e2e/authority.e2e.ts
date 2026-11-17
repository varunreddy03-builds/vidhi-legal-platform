import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Runs only against a server started with AUTHORITY_CHECK_ENABLED=true (no case-source token: every case ends as "could not check").
test.skip(process.env.AUTHORITY_CHECK_ENABLED !== "true", "Authority Check is off on this server");

const DRAFT = "The accused relies on Rangappa v. Sri Mohan (2010) 11 SCC 441. The complaint is under Section 138 of the Negotiable Instruments Act, 1881 and Section 420 of the Indian Penal Code.";

test("Authority Check: paste a draft, read the honest result, record a decision, download", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await page.getByTestId("toolkit-authority").locator("a").click();
  await expect(page.getByTestId("authority-notice")).toContainText("not legal advice");
  await expect(page.getByTestId("authority-notice")).toContainText("still good law is not checked");

  await page.getByTestId("authority-title-input").fill("Reply to notice");
  await page.getByTestId("authority-text-input").fill(DRAFT);
  await page.getByTestId("authority-run").click();

  await expect(page.getByTestId("authority-report")).toBeVisible({ timeout: 30_000 }); // the first check on a cold server can take 8 s
  await expect(page.getByTestId("authority-summary")).toContainText("3 references (1 cases, 2 statutes)");
  await expect(page.getByTestId("authority-current-status")).toContainText("current status: not checked");
  await expect(page.getByTestId("authority-kept")).toContainText(/Kept until 20\d\d-\d\d-\d\d, then deleted automatically/); // reports expire on their own
  const refs = page.getByTestId("authority-ref");
  await expect(refs).toHaveCount(3);
  // on a laptop both panes show at once: the draft's references on the left, what the source shows on the right
  await expect(page.getByTestId("authority-list-pane")).toBeVisible();
  await expect(page.getByTestId("authority-detail")).toBeVisible();
  await expect(refs.first().getByTestId("authority-ref-label")).toHaveText("Could not check"); // the source is not configured: never "not found"
  await expect(page.getByTestId("authority-ref-label").filter({ hasText: "Not found after a full search" })).toHaveCount(0); // no reference gets this label (the labels legend names it, so the check is on the reference labels)
  await expect(page.getByTestId("authority-detail")).not.toContainText("Not found after a full search");
  await refs.nth(2).click();
  await expect(page.getByText("does not convert section numbers")).toBeVisible(); // the old-code note

  await refs.nth(0).click();
  await page.getByTestId("authority-fix").click();
  await page.getByTestId("authority-fix-note").fill("Check the volume number");
  await page.getByTestId("authority-fix-save").click();
  await expect(refs.nth(0).getByTestId("authority-ref-state")).toContainText("Marked to fix");
  await refs.nth(1).click();
  await page.getByTestId("authority-accept").click();
  await expect(refs.nth(1).getByTestId("authority-ref-state")).toContainText("Accepted as is");
  await refs.nth(2).click();
  await page.getByTestId("authority-reviewed").click();
  await expect(page.getByTestId("authority-summary")).toContainText("0 still open");

  await page.reload(); // the decisions are saved on the server
  await expect(page.getByTestId("authority-ref").nth(0).getByTestId("authority-ref-state")).toContainText("Marked to fix");

  const [download] = await Promise.all([page.waitForEvent("popup").catch(() => null), page.getByTestId("authority-export-docx").click()]);
  void download; // browsers open the file in a new tab; the file itself is checked by the backend tests

  await page.getByTestId("authority-delete").click(); // the person who made the check can remove it
  await expect(page.getByTestId("authority-list")).toBeVisible();
  await expect(page.getByTestId("authority-row")).toHaveCount(0);
});

test("Authority Check on a phone: one pane at a time with a Back button, nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/katalyst/authority");
  await page.getByTestId("authority-text-input").fill(DRAFT);
  await page.getByTestId("authority-run").click();
  await expect(page.getByTestId("authority-report")).toBeVisible();
  await expect(page.getByTestId("authority-list-pane")).toBeVisible();
  await expect(page.getByTestId("authority-detail")).toBeHidden();
  await page.getByTestId("authority-ref").first().click();
  await expect(page.getByTestId("authority-detail")).toBeVisible();
  await expect(page.getByTestId("authority-list-pane")).toBeHidden();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.getByTestId("authority-back-to-list").click();
  await expect(page.getByTestId("authority-list-pane")).toBeVisible();
  await expect(page.getByTestId("authority-detail")).toBeHidden();
});

test("Authority Check from a file: choose a draft, get the report; the keyboard can open the picker", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst/authority");
  await page.getByTestId("authority-file").focus();
  await expect(page.getByTestId("authority-file")).toBeFocused(); // a real tab stop, labelled by its text
  await page.getByTestId("authority-file-input").setInputFiles({ name: "తెలుగు draft.txt", mimeType: "text/plain", buffer: Buffer.from("తెలుగు వాక్యం. " + DRAFT, "utf-8") });
  await expect(page.getByTestId("authority-report")).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId("authority-summary")).toContainText("3 references");
});

test("a document can be uploaded into a matter with the new upload box", async ({ page }) => {
  await signUp(page);
  const title = `Upload ${Date.now().toString(36)}`;
  await page.goto("/matters");
  await page.getByTestId("new-matter-button").click();
  await page.getByTestId("matter-title-input").fill(title);
  await page.getByTestId("matter-parties-input").fill("A v. B");
  await page.getByTestId("matter-submit-button").click();
  await page.getByTestId("matter-row").filter({ hasText: title }).click();
  await page.getByRole("tab", { name: /documents/i }).click();
  await page.getByTestId("document-upload-input").setInputFiles({ name: "note.txt", mimeType: "text/plain", buffer: Buffer.from("The tenant paid Rs 20,000 rent on 1 January.", "utf-8") });
  await expect(page.getByText("note.txt").first()).toBeVisible({ timeout: 30000 });
});
