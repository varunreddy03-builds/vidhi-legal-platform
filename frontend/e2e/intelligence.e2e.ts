import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// The AI keys are not set on the test server, so the answer is supplied by the browser; the real research flow is tested on the server.
const ANSWER = {
  id: "r-1", organization_id: "o", matter_id: null, question: "Invented question about a rent paper", mode: "STANDARD",
  answer: "Invented answer text.", contrary_authority: [], uncertainty: "", matter_context_used: [], coverage: {},
  missing_information: ["Invented: the date of the paper"], unresolved_evidence: [], unverified_references: [], neutral_adjusted: false,
  capabilities_used: ["stand-in"], disclaimer: "Invented disclaimer.", created_by: "u", created_at: "2026-10-30T10:00:00Z",
  claims: [
    { id: "c1", text: "Invented claim one", claim_kind: "FACTUAL", verification_status: "VERIFIED", note: "Found.", citations: [{ citation: "Invented source", doc_label: "Invented paper", page: 2, passage: "invented words", quote_verified: true, authority_level: "DOCUMENT" }], conflicts: [], human_review_required: false },
    { id: "c2", text: "Invented claim two", claim_kind: "LEGAL", verification_status: "UNSUPPORTED", note: "No source.", citations: [], conflicts: [], human_review_required: true },
  ],
};

test("Ask a question: the answer says how much was backed by a source, numbers each point, and offers the deeper research view", async ({ page }) => {
  await page.route("**/api/research", (route) => (route.request().method() === "POST" ? route.fulfill({ json: ANSWER }) : route.fulfill({ json: [] })));
  await signUp(page);
  await page.goto("/ask?q=Invented question about a rent paper");
  await expect(page.getByTestId("ask-input")).toHaveValue("Invented question about a rent paper");
  await page.getByTestId("ask-submit").click();
  await expect(page.getByTestId("ask-answer")).toContainText("Invented answer text.");
  await expect(page.getByTestId("ask-honesty")).toContainText("1 of 2 points are backed up by a real source");
  await page.getByTestId("ask-sources").locator("summary").click();
  await expect(page.getByTestId("ask-sources")).toContainText("1.");
  await expect(page.getByTestId("ask-sources")).toContainText("2.");
  await expect(page.getByTestId("ask-go-deeper")).toHaveAttribute("href", /\/research\?q=Invented/);
  await expect(page.getByText(/\bsafe to rely\b|\bwill win\b|\blied\b/i)).toHaveCount(0);
});

test("Research on a laptop: the answer box keeps a readable width, claims are numbered, and nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.route("**/api/research", (route) => (route.request().method() === "POST" ? route.fulfill({ json: ANSWER }) : route.fulfill({ json: [] })));
  await signUp(page);
  await page.goto("/research?q=Invented question about a rent paper");
  await expect(page.getByTestId("research-question-input")).toHaveValue("Invented question about a rent paper");
  await page.getByTestId("research-submit-button").click();
  await expect(page.getByTestId("research-claim")).toHaveCount(2);
  await expect(page.getByTestId("claim-number").first()).toHaveText("1.");
  const box = await page.getByTestId("research-answer").boundingBox();
  expect(box!.width).toBeGreaterThan(520); // it used to shrink to a thin strip beside two other columns
  await page.getByTestId("research-claim").first().click();
  await expect(page.getByTestId("source-card")).toContainText("Invented source");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
