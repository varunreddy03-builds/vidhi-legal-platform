import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Slice 2 of the redesign (docs/PLAN_REDESIGN.md): one account menu in the top bar, answers in a serif, dark by default, nothing overflowing on a phone.
// The AI keys are not set on the test server, so the answer is supplied by the browser.
const ANSWER = {
  id: "r-look", organization_id: "o", matter_id: null, question: "Invented look question", mode: "STANDARD",
  answer: "Invented answer text for the look test.", contrary_authority: [], uncertainty: "", matter_context_used: [], coverage: {},
  missing_information: [], unresolved_evidence: [], unverified_references: [], neutral_adjusted: false,
  capabilities_used: ["stand-in"], disclaimer: "Invented disclaimer.", created_by: "u", created_at: "2026-10-30T10:00:00Z",
  claims: [{ id: "c1", text: "Invented claim", claim_kind: "LEGAL", verification_status: "UNSUPPORTED", note: "No source.", citations: [], conflicts: [], human_review_required: true }],
};

test("a new visitor sees the dark theme, and the account menu holds plan, theme, language, settings and sign out", async ({ page }) => {
  await signUp(page);
  await expect(page.locator("html")).toHaveClass(/dark/);
  // the bar itself no longer carries the plan badge, the organisation name beside a sign-out icon, or language and theme buttons
  await expect(page.getByTestId("plan-badge")).toHaveCount(0);
  await expect(page.getByTestId("sign-out-button")).toHaveCount(0);
  await page.getByTestId("account-menu").click();
  await expect(page.getByTestId("plan-badge")).toHaveText("FREE");
  await page.getByTestId("theme-light").click();
  await expect(page.locator("html")).toHaveClass(/light/);
  await page.getByTestId("account-language").locator("summary").click();
  await page.getByTestId("lang-hi").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "hi");
  await page.getByTestId("account-menu").click();
  await expect(page.getByTestId("account-settings")).toBeVisible();
  await expect(page.getByTestId("sign-out-button")).toBeVisible();
});

test("on a phone the account menu fits the screen and the page does not scroll sideways", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  for (const route of ["/start", "/intelligence", "/ask", "/research", "/katalyst"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow, `${route} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(0);
  }
  await page.getByTestId("account-menu").click();
  const box = await page.getByTestId("account-settings").boundingBox();
  expect(box && box.x >= 0 && box.x + box.width <= 375, "the menu stays inside a 375 px screen").toBeTruthy();
});

test("the answer text is set in a serif font, the interface in a sans", async ({ page }) => {
  await page.route("**/api/research", (route) => (route.request().method() === "POST" ? route.fulfill({ json: ANSWER }) : route.fulfill({ json: [] })));
  await signUp(page);
  await page.goto("/ask?q=Invented look question");
  await page.getByTestId("ask-submit").click();
  const answer = page.getByTestId("ask-answer-text");
  await expect(answer).toContainText("Invented answer text");
  expect(await answer.evaluate((el) => getComputedStyle(el).fontFamily)).toContain("Lora");
  expect(await page.getByTestId("page-title").evaluate((el) => getComputedStyle(el).fontFamily)).not.toContain("Lora");
});
