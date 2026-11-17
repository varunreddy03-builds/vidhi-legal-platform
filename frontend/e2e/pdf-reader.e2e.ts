import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// The in-page PDF reader (frontend/src/components/matter/PdfReader.tsx): opens a matter's PDF, turns pages, searches with marks on the page, keeps bookmarks on this device.
const FIXTURE = fileURLToPath(new URL("./fixtures/two-page-dates.pdf", import.meta.url));

test("a matter's PDF opens in the page, can be searched, bookmarked and turned page by page", async ({ page }) => {
  await signUp(page);
  const m = await (await page.request.post("/api/matters", { data: { title: "Reader matter", parties: "A v B", description: "Reading a PDF." } })).json();
  await page.goto(`/matters/${m.id}`);
  await page.getByTestId("tab-documents").click();
  await page.getByTestId("document-upload-input").setInputFiles(FIXTURE);
  await expect(page.getByText("two-page-dates.pdf").first()).toBeVisible({ timeout: 30_000 });

  await page.getByTestId("read-pdf").first().click();
  const reader = page.getByTestId("pdf-reader");
  await expect(reader).toBeVisible();
  await expect(reader.getByText(/of 2/)).toBeVisible({ timeout: 30_000 });
  await expect(reader.getByRole("img", { name: "Page 1 of 2" })).toBeVisible();

  // search: the word is only on page 2; the match is listed and the page jumps there
  await reader.getByTestId("pdf-search").fill("agreement");
  await expect(reader.getByTestId("pdf-hits")).toContainText("Found on 1 page: 2", { timeout: 15_000 });
  await reader.getByRole("button", { name: "Next match" }).click();
  await expect(reader.getByRole("img", { name: "Page 2 of 2" })).toBeVisible();
  await expect(reader.getByTestId("pdf-mark").first()).toBeVisible({ timeout: 15_000 }); // the word is marked on the page
  await reader.getByTestId("pdf-search").fill("zzzz-not-there");
  await expect(reader.getByTestId("pdf-hits")).toHaveText("No match", { timeout: 15_000 });
  await reader.getByTestId("pdf-search").fill("");

  // bookmark page 2, go back to page 1, come back with the bookmark
  await reader.getByTestId("pdf-bookmark").click();
  await expect(reader.getByTestId("pdf-bookmark")).toHaveAttribute("aria-pressed", "true");
  await reader.getByRole("button", { name: "Previous page" }).click();
  await expect(reader.getByRole("img", { name: "Page 1 of 2" })).toBeVisible();
  await reader.getByRole("button", { name: "p. 2" }).click();
  await expect(reader.getByRole("img", { name: "Page 2 of 2" })).toBeVisible();

  // a note on page 2 is saved with the document, shows on that page only, and can be removed
  // pick a passage on the page itself (the page has a selectable text layer), use it for the note, and see it marked in blue afterwards.
  // The text layer is redrawn after the page picture changes: wait until it shows PAGE 2's own words, or a slow machine picks a sentence of page 1 and loses the selection when the layer redraws.
  await expect(reader.getByTestId("pdf-text-layer")).toContainText("agreement", { timeout: 15_000 });
  await expect(reader.getByTestId("pdf-text-layer")).not.toContainText("Page one has only ordinary words");
  const picked = await reader.getByTestId("pdf-text-layer").evaluate((layer) => {
    const span = Array.from(layer.querySelectorAll("span")).find((el) => /\S{4,}/.test(el.textContent ?? ""));
    if (!span) return "";
    const range = document.createRange();
    range.selectNodeContents(span);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    return (span.textContent ?? "").replace(/\s+/g, " ").trim();
  });
  expect(picked.length).toBeGreaterThan(3);
  await reader.getByTestId("pdf-use-selection").click();
  await expect(reader.getByTestId("pdf-note-quote")).toHaveValue(picked);
  await reader.getByTestId("pdf-note-text").fill("Check this date against the notice.");
  await reader.getByTestId("pdf-note-add").click();
  await expect(reader.getByTestId("pdf-note")).toContainText("Check this date against the notice.");
  await expect(reader.getByTestId("pdf-note")).toContainText(picked);
  await expect(reader.getByTestId("pdf-saved-mark").first()).toBeVisible({ timeout: 15_000 });
  await reader.getByRole("button", { name: "Previous page" }).click();
  await expect(reader.getByTestId("pdf-note")).toHaveCount(0); // page 1 has none
  await reader.getByRole("button", { name: "Next page" }).click();
  await expect(reader.getByTestId("pdf-note")).toHaveCount(1);
  await page.keyboard.press("Escape");
  await page.getByTestId("read-pdf").first().click();
  await expect(reader.getByRole("img", { name: "Page 1 of 2" })).toBeVisible({ timeout: 30_000 });
  await reader.getByRole("button", { name: "Next page" }).click();
  await expect(reader.getByTestId("pdf-note")).toHaveCount(1); // still there after closing and reopening
  await reader.getByRole("button", { name: /Delete note/ }).click();
  await expect(reader.getByTestId("pdf-note")).toHaveCount(0);

  await scan(page, "PDF reader");
  await page.keyboard.press("Escape");
  await expect(reader).toBeHidden();
});

test("the reader is only offered for PDFs", async ({ page }) => {
  await signUp(page);
  const m = await (await page.request.post("/api/matters", { data: { title: "Text matter", parties: "A v B", description: "A text file." } })).json();
  await page.goto(`/matters/${m.id}`);
  await page.getByTestId("tab-documents").click();
  await page.getByTestId("document-upload-input").setInputFiles({ name: "note.txt", mimeType: "text/plain", buffer: Buffer.from("Hearing on 12 March 2021.") });
  await expect(page.getByText("note.txt").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("read-pdf")).toHaveCount(0);
});
