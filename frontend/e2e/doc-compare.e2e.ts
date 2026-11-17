import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Comparing two versions of a document in a matter (frontend/src/components/matter/DocCompare.tsx).
test("two versions of a document can be compared and the changes are shown in words as well as colour", async ({ page }) => {
  await signUp(page);
  const m = await (await page.request.post("/api/matters", { data: { title: "Compare matter", parties: "A v B", description: "Two versions." } })).json();
  await page.goto(`/matters/${m.id}`);
  await page.getByTestId("tab-documents").click();
  await expect(page.getByTestId("doc-compare")).toHaveCount(0); // needs two readable documents
  const send = async (name: string, text: string, total: number) => {
    await page.getByTestId("document-upload-input").setInputFiles({ name, mimeType: "text/plain", buffer: Buffer.from(text) });
    await expect(page.getByTestId("download-original")).toHaveCount(total, { timeout: 30_000 });
  };
  await send("agreement-v1.txt", "Payment is due within thirty days of the invoice.", 1);
  await expect(page.getByTestId("doc-compare")).toHaveCount(0);
  await send("agreement-v2.txt", "Payment is due within forty five days of the invoice.", 2);
  const panel = page.getByTestId("doc-compare");
  await expect(panel).toBeVisible();
  await expect(panel.getByTestId("compare-run")).toBeDisabled();
  await panel.getByTestId("compare-first").selectOption({ label: "agreement-v1.txt" });
  await panel.getByTestId("compare-second").selectOption({ label: "agreement-v2.txt" });
  await panel.getByTestId("compare-run").click();
  const result = panel.getByTestId("compare-result");
  await expect(result).toContainText("words added");
  await expect(result.getByTestId("compare-deleted")).toContainText("thirty");
  await expect(result.getByTestId("compare-added")).toContainText("forty five");
  await expect(result.getByTestId("compare-deleted")).toContainText("[deleted:"); // read out by a screen reader, not only coloured
  await scan(page, "document comparison");
});
