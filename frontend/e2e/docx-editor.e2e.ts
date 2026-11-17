import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// The Word editor (components/matter/DocxEditor.tsx): edit a .docx's text, save it as a NEW document, the original stays.
test("a Word file's text can be edited and is saved as a new document", async ({ page }) => {
  await signUp(page);
  const m = await (await page.request.post("/api/matters", { data: { title: "Word matter", parties: "A v B", description: "Editing a Word file." } })).json();
  await page.goto(`/matters/${m.id}`);
  await page.getByTestId("tab-documents").click();
  await page.getByTestId("document-upload-input").setInputFiles("e2e/fixtures/sample-notice.docx");
  await expect(page.getByText("sample-notice.docx").first()).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("edit-docx").first().click();
  const editor = page.getByTestId("docx-editor");
  await expect(editor).toBeVisible();
  const first = editor.getByTestId("docx-paragraph").first();
  await expect(first).toHaveValue(/notice/i, { timeout: 15_000 });
  await expect(editor.getByTestId("docx-save")).toBeDisabled();
  await first.fill("Edited first paragraph.");
  await editor.getByTestId("docx-save").click();
  await expect(page.getByTestId("edit-docx")).toHaveCount(2, { timeout: 30_000 }); // the new copy is listed beside the original
  await page.getByTestId("edit-docx").first().click();
  await scan(page, "Word editor");
});
