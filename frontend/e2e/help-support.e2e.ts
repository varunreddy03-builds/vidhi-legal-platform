import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// Help centre pages for the real tasks (English only so far, and the page says so) and a support message that carries only what the person types.

test("the help centre has pages for the real tasks, says which are English only, and can be searched; also on a phone", async ({ page }) => {
  await signUp(page);
  await page.goto("/help");
  await page.getByTestId("help-language").selectOption("hi");
  await expect(page.getByTestId("help-note")).toBeVisible(); // the Hindi text is marked as an unreviewed translation
  await expect(page.getByTestId("help-english-only")).toContainText("English only so far");
  const extra = page.getByTestId("help-item-extra");
  expect(await extra.count()).toBeGreaterThanOrEqual(17);
  await expect(page.getByRole("heading", { name: "Checking a draft" })).toBeVisible();

  await page.getByRole("textbox").first().fill("scanned");
  await expect(extra).toHaveCount(1);
  await expect(extra.first()).toContainText("Can VIDHI read a scanned document?");
  await extra.first().locator("summary").click();
  await expect(extra.first()).toContainText("marked as uncertain");
  await page.getByRole("textbox").first().fill("zzzz-no-such-thing");
  await expect(page.getByTestId("help-item")).toHaveCount(0); // nothing matches, in the Hindi page too (its "nothing matches" line is Hindi)
  await expect(extra).toHaveCount(0);
  await page.getByRole("textbox").first().fill("");

  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await scan(page, "help centre on a phone");
});

test("a support message carries only what the person typed, never anything from their matters", async ({ page }) => {
  await signUp(page);
  const SECRET = "Confidential client Ramesh Babu Constructions";
  const m = await (await page.request.post("/api/matters", { data: { title: SECRET, parties: SECRET, description: SECRET } })).json();
  await page.request.post("/api/drafts", { data: { matter_id: m.id, title: SECRET, body: SECRET } });

  let sent: Record<string, unknown> | null = null;
  // the server allows 5 support messages an hour per address, so the request is answered here: this test is about what the page sends
  await page.route("**/api/public/support", async (route) => {
    sent = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true, reference: "abc12345" } });
  });
  await page.goto("/matters/" + m.id); // the matter is open on screen when the person asks for help
  await page.goto("/support");
  await expect(page.getByText("VIDHI never adds anything from your matters to this message")).toBeVisible();
  await page.getByTestId("support-message").fill("The upload button did not respond on my phone.");
  await page.getByTestId("support-send").click();
  await expect(page.getByTestId("support-sent")).toBeVisible();

  expect(sent).not.toBeNull();
  expect(Object.keys(sent!).sort()).toEqual(["category", "email", "message", "name", "website"]);
  expect(JSON.stringify(sent)).not.toContain("Ramesh");
  expect((sent as unknown as { message: string }).message).toBe("The upload button did not respond on my phone.");
});
