import { expect, test, type Page } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Numbered source chips under an Ask answer open the point's sources beside the answer (frontend/src/components/CitationPanel.tsx). The answer is supplied by the browser; all names are invented.
const SOURCE_TEXT = "Section 1. A widget must be tested before it is sold. The tester shall keep a record of each test for two years.";
const ANSWER = {
  id: "r-2", organization_id: "o", matter_id: null, question: "Invented question about widgets", mode: "STANDARD",
  answer: "Invented answer about widgets.", contrary_authority: [], uncertainty: "", matter_context_used: [], coverage: {},
  missing_information: [], unresolved_evidence: [], unverified_references: [], neutral_adjusted: false,
  capabilities_used: ["stand-in"], disclaimer: "Invented disclaimer.", created_by: "u", created_at: "2026-10-30T10:00:00Z",
  claims: [
    {
      id: "c1", text: "A widget must be tested before sale.", claim_kind: "LEGAL", verification_status: "VERIFIED", note: "Found.", conflicts: [], human_review_required: false,
      citations: [{
        citation: "Section 1 of the Fictional Widget Testing Act, 2000", authority_level: "PRIMARY", verification_status: "VERIFIED", passage: "A widget must be tested before it is sold.", document_id: null, page: null,
        library_id: "widget-act-1", doc_label: null, quote_verified: true, source_name: "Invented Official Gazette", source_url: "https://example.org/widget-act", version: "2000 original",
        verified_by: "Invented Reviewer", verified_on: "2026-11-01", source_text: SOURCE_TEXT,
      }],
    },
    { id: "c2", text: "Invented claim with no source.", claim_kind: "LEGAL", verification_status: "UNSUPPORTED", note: "No source.", citations: [], conflicts: [], human_review_required: true },
  ],
};

async function ask(page: Page) {
  await page.route("**/api/research", (route) => (route.request().method() === "POST" ? route.fulfill({ json: ANSWER }) : route.fulfill({ json: [] })));
  await signUp(page);
  await page.goto("/ask?q=Invented question about widgets");
  await page.getByTestId("ask-submit").click();
  await expect(page.getByTestId("ask-answer")).toContainText("Invented answer about widgets.");
}

test("a numbered chip opens the source, version, reviewer, link and the passage with the checked words marked (desktop, light and dark)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    if (scheme === "light") await ask(page);
    await page.getByTestId("citation-chip").first().click();
    const sheet = page.getByTestId("citation-sheet");
    await expect(sheet).toBeVisible();
    await expect(sheet).toContainText("Section 1 of the Fictional Widget Testing Act, 2000");
    await expect(sheet).toContainText("Invented Official Gazette, version 2000 original");
    await expect(sheet).toContainText("Compared with the source by Invented Reviewer on 2026-11-01");
    await expect(sheet.getByRole("link", { name: "Open the official source" })).toHaveAttribute("href", "https://example.org/widget-act");
    await expect(sheet.getByTestId("citation-mark")).toHaveText("A widget must be tested before it is sold.");
    await expect(sheet).toContainText("found exactly in the source");
    const box = await sheet.boundingBox();
    expect(box && box.x > 600).toBeTruthy(); // beside the answer, on the right
    await scan(page, `citation panel ${scheme}`);
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
  }
});

test("a point without a source says it could not be checked", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await ask(page);
  await page.getByTestId("citation-chip").nth(1).click();
  await expect(page.getByTestId("citation-sheet")).toContainText("No source was found for this point, so it could not be checked.");
});

test("on a 375 px phone the sources open as a sheet from the bottom, nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await ask(page);
  await page.getByTestId("citation-chip").first().click();
  const sheet = page.getByTestId("citation-sheet");
  await expect(sheet).toBeVisible();
  const box = await sheet.boundingBox();
  expect(box && box.y > 100 && box.width >= 370).toBeTruthy(); // full width, rising from the bottom
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await scan(page, "citation panel phone");
});
