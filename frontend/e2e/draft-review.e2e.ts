import { execFileSync } from "node:child_process";
import { expect, test, type Browser } from "@playwright/test";
import { scan, signUp } from "./helpers";

// A junior writes a draft and sends it for review; a senior approves it, comments, asks for changes; the junior sees it. All on a 375 px phone.
// The two colleagues are added to the owner's organisation straight in the test database (their session tokens come back from the seed script).
const PY = process.env.E2E_PYTHON ?? "C:/vidhi-tools/venv2/Scripts/python.exe";
const env = { ...process.env, DB_NAME: process.env.E2E_DB_NAME ?? "vidhi_e2e", MONGO_URL: process.env.E2E_MONGO_URL ?? "mongodb://127.0.0.1:27017" };
const seed = (email: string, role: string, name: string) => execFileSync(PY, ["-I", "../scripts/e2e_seed_member.py", email, role, name], { env, encoding: "utf-8" }).trim();

async function asPerson(browser: Browser, token: string) {
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  await ctx.addCookies([{ name: "vidhi_session", value: token, domain: "localhost", path: "/" }]);
  return { ctx, page: await ctx.newPage() };
}

test("a junior sends a draft, a senior comments, asks for changes, then approves; an edit after approval sends it back", async ({ browser, page }) => {
  test.setTimeout(240_000);
  const owner = await signUp(page);
  const junior = await asPerson(browser, seed(owner.email, "MEMBER", "Juno Junior"));
  const senior = await asPerson(browser, seed(owner.email, "LAWYER", "Sena Senior"));

  const d = await (await junior.page.request.post("/api/drafts", { data: { title: "Reply to the notice", body: "We deny the claim." } })).json();
  await junior.page.goto(`/drafts/${d.id}`);
  await expect(junior.page.getByTestId("review-status")).toHaveText("Draft");
  await expect(junior.page.getByTestId("review-approve")).toHaveCount(0); // a junior has no approve button
  await junior.page.getByTestId("review-send").click();
  await expect(junior.page.getByTestId("review-status")).toHaveText("With a reviewer");
  await expect(junior.page.getByTestId("review-line")).toContainText("Sent for review by Juno Junior");

  await senior.page.goto(`/drafts/${d.id}`);
  await expect(senior.page.getByTestId("review-status")).toHaveText("With a reviewer");
  await senior.page.getByTestId("comment-input").fill("Please cite the invoice number.");
  await senior.page.getByTestId("comment-add").click();
  await expect(senior.page.getByTestId("comment")).toContainText("Please cite the invoice number.");
  await senior.page.getByTestId("review-ask-changes").click();
  await expect(senior.page.getByTestId("review-send-changes")).toBeDisabled(); // a reason is needed
  await senior.page.getByTestId("review-reason").fill("Add the invoice number.");
  await senior.page.getByTestId("review-send-changes").click();
  await expect(senior.page.getByTestId("review-status")).toHaveText("Changes requested");

  await junior.page.reload();
  await expect(junior.page.getByTestId("review-line")).toContainText("Sena Senior asked for changes");
  await expect(junior.page.getByTestId("review-line")).toContainText("Add the invoice number.");
  await expect(junior.page.getByTestId("comment")).toContainText("Please cite the invoice number.");
  await junior.page.getByTestId("draft-editor-body").fill("We deny the claim. Invoice SMP-0042.");
  await junior.page.getByTestId("draft-save-button").click();
  await expect(junior.page.getByTestId("draft-save-button")).toHaveText("Saved");
  await junior.page.getByTestId("comment-resolve").click();
  await expect(junior.page.getByTestId("comment")).toContainText("resolved by Juno Junior");
  await junior.page.getByTestId("review-send").click();
  await expect(junior.page.getByTestId("review-status")).toHaveText("With a reviewer");

  await senior.page.reload();
  await senior.page.getByTestId("review-approve").click();
  await expect(senior.page.getByTestId("review-status")).toHaveText("Approved");
  await expect(senior.page.getByTestId("review-line")).toContainText("Approved by Sena Senior on");
  expect(await senior.page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await junior.page.reload();
  await expect(junior.page.getByTestId("review-status")).toHaveText("Approved");
  await junior.page.getByTestId("draft-editor-body").fill("We deny the claim. Invoice SMP-0042. Added line.");
  await junior.page.getByTestId("draft-save-button").click();
  await expect(junior.page.getByTestId("review-status")).toHaveText("Draft");
  await expect(junior.page.getByTestId("review-line")).toContainText("Changed after it was approved");
  await scan(junior.page, "draft with the review panel on a phone");
  await junior.ctx.close();
  await senior.ctx.close();
});

test("the other organisation cannot see the draft, its status or its comments", async ({ browser, page }) => {
  const owner = await signUp(page);
  const d = await (await page.request.post("/api/drafts", { data: { title: "Private", body: "Private text." } })).json();
  await page.request.post(`/api/drafts/${d.id}/comments`, { data: { text: "Private comment." } });
  const other = await browser.newContext();
  const stranger = await other.newPage();
  await signUp(stranger);
  for (const path of [`/api/drafts/${d.id}/review`, `/api/drafts/${d.id}/comments`]) expect((await stranger.request.get(path)).status()).toBe(404);
  expect((await stranger.request.post(`/api/drafts/${d.id}/review`, { data: { decision: "approve" } })).status()).toBe(404);
  await stranger.goto(`/drafts/${d.id}`);
  await expect(stranger.getByText("Private comment.")).toHaveCount(0);
  expect(owner.email).toBeTruthy();
  await other.close();
});
