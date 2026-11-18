import { expect, test } from "@playwright/test";
import { scan, signUp, unique } from "./helpers";

// Connections. The browser tests run Microsoft as a pretend (MS_STUB), so the sign-in screen at Microsoft is skipped: the test makes the request Microsoft would redirect back with.
// What is read, kept and refused is tested on the server (backend/tests/test_connectors.py). iManage is not built and the page says so.

test("the connections page is honest, and Microsoft files and mail can be copied into a matter", async ({ page }) => {
  await signUp(page);
  await page.goto("/connections");
  await expect(page.getByTestId("conn-state-imanage")).toHaveText("Not available");
  await expect(page.getByTestId("conn-imanage")).toContainText("Not built");
  await expect(page.getByTestId("conn-state-word")).toHaveText("Available");
  await expect(page.getByTestId("conn-state-microsoft")).toHaveText("Not connected");

  const start = await page.request.get("/api/connectors/microsoft/start", { maxRedirects: 0 });
  expect(start.status()).toBe(302);
  const state = new URL(start.headers()["location"]).searchParams.get("state");
  await page.goto(`/api/connectors/microsoft/callback?code=stub-code&state=${state}`);
  await expect(page).toHaveURL(/\/connections\?microsoft=connected/);
  await expect(page.getByTestId("ms-flash")).toContainText("Connected");
  await expect(page.getByTestId("conn-state-microsoft")).toHaveText("Connected");
  await expect(page.getByTestId("ms-account")).toContainText("stub.user@example.test");
  await expect(page.getByTestId("ms-files")).toContainText("lease.txt");
  await expect(page.getByTestId("ms-mail")).toContainText("Notice of termination");

  const m = await page.request.post("/api/matters", { data: { title: `Conn ${unique()}`, description: "", parties: "", jurisdiction_id: "IN" } });
  const matter = (await m.json()) as { id: string; title: string };
  await page.reload();
  await expect(page.getByTestId("ms-import-file")).toBeDisabled(); // choose a matter first
  await page.getByTestId("ms-matter").selectOption(matter.id);
  await scan(page, "Connections page, Microsoft connected");
  await page.getByTestId("ms-import-file").click();
  await expect.poll(async () => ((await (await page.request.get(`/api/matters/${matter.id}/documents`)).json()) as { filename: string }[]).map((d) => d.filename)).toContain("lease.txt");
  await page.getByTestId("ms-import-mail").click();
  await expect.poll(async () => ((await (await page.request.get(`/api/matters/${matter.id}/documents`)).json()) as { filename: string }[]).length).toBe(2);

  await page.getByTestId("ms-disconnect").click();
  await expect(page.getByTestId("conn-state-microsoft")).toHaveText("Not connected");
  await page.setViewportSize({ width: 375, height: 812 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
