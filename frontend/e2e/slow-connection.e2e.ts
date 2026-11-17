import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { signUp } from "./helpers";

// A slow and dropping connection (docs/connection/; how fast the first screen loads on a slow phone is measured separately, on the production build, by frontend/scripts/perf.mjs): a 400 kbit/s line with a 400 ms round trip, and the connection cut in the middle of work.
// Uploads must arrive after a short drop or fail in words that say what to do (and keep the file); drafts must keep what was typed; errors must say what to do next.
const SLOW = { offline: false, latency: 400, downloadThroughput: (400 * 1024) / 8, uploadThroughput: (400 * 1024) / 8 };

async function throttle(page: Page, on: boolean) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", on ? SLOW : { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  return cdp;
}
const offline = (ctx: BrowserContext, on: boolean) => ctx.setOffline(on);
// about 300 KB of plain text: at 50 KB/s up that takes six seconds, long enough to cut the line in the middle
const BIG = Buffer.from("The cheque dated 01/06/2021 was returned unpaid by the bank. ".repeat(5000));

async function matterWithPage(page: Page) {
  await signUp(page);
  const m = await (await page.request.post("/api/matters", { data: { title: "Slow line matter", parties: "A v B", description: "A returned cheque." } })).json();
  return m.id as string;
}

test("an upload cut for a moment arrives by itself, without choosing the file again", async ({ page }) => {
  test.setTimeout(240_000);
  const id = await matterWithPage(page);
  await page.goto(`/matters/${id}`);
  await page.getByTestId("tab-documents").click();
  await throttle(page, true);
  await page.getByTestId("document-upload-input").setInputFiles({ name: "slow-upload.txt", mimeType: "text/plain", buffer: BIG });
  await expect(page.getByTestId("document-upload")).toContainText(/Uploading/); // progress is shown, not a frozen screen
  await expect.poll(async () => Number(((await page.getByRole("progressbar", { name: /upload/i }).getAttribute("aria-valuenow").catch(() => "0")) ?? "0")), { timeout: 60_000 }).toBeGreaterThan(10);
  await offline(page.context(), true);
  await page.waitForTimeout(1500);
  await offline(page.context(), false);
  await expect(page.getByText("slow-upload.txt").first()).toBeVisible({ timeout: 120_000 });
});

test("an upload cut for a long time fails in words that say what to do, keeps the file, and sends it again by itself when the connection returns", async ({ page }) => {
  test.setTimeout(300_000);
  const id = await matterWithPage(page);
  await page.goto(`/matters/${id}`);
  await page.getByTestId("tab-documents").click();
  await throttle(page, true);
  await page.getByTestId("document-upload-input").setInputFiles({ name: "slow-upload.txt", mimeType: "text/plain", buffer: BIG });
  await expect.poll(async () => Number(((await page.getByRole("progressbar", { name: /upload/i }).getAttribute("aria-valuenow").catch(() => "0")) ?? "0")), { timeout: 60_000 }).toBeGreaterThan(10);
  await offline(page.context(), true);
  const status = page.getByTestId("document-upload-status");
  await expect(status).toContainText(/not sent|could not send|did not go/i, { timeout: 60_000 });
  await expect(status).toContainText(/kept|still here|saved on this/i); // the person knows the file is not lost
  await expect(status).toContainText(/connection|signal|internet/i);
  await expect(page.getByTestId("document-upload-retry")).toBeVisible();
  await offline(page.context(), false);
  // no tap needed: the app notices the connection is back
  await expect(page.getByText("slow-upload.txt").first()).toBeVisible({ timeout: 120_000 });
});

test("a draft is saved while typing, shows its state in words, and keeps the text when the line drops", async ({ page }) => {
  test.setTimeout(240_000);
  const id = await matterWithPage(page);
  const d = await (await page.request.post("/api/drafts", { data: { matter_id: id, title: "Letter", body: "first" } })).json();
  await page.goto(`/drafts/${d.id}`);
  const body = page.getByTestId("draft-editor-body");
  const status = page.getByTestId("draft-status");
  await expect(status).toContainText(/saved/i);
  await body.fill("first, then typed on a train");
  await expect(status).toContainText(/saving|unsaved|not saved yet/i);
  // saved on the server without pressing Save
  await expect.poll(async () => (await (await page.request.get(`/api/drafts/${d.id}`)).json()).body, { timeout: 40_000 }).toBe("first, then typed on a train");
  await expect(status).toContainText(/all changes saved/i);
  // the line drops while typing
  await offline(page.context(), true);
  await body.fill("first, then typed on a train, and while the signal was gone");
  await expect(status).toContainText(/no connection/i, { timeout: 40_000 });
  await expect(status).toContainText(/kept on this (phone|device)/i);
  await offline(page.context(), false);
  await expect.poll(async () => (await (await page.request.get(`/api/drafts/${d.id}`)).json()).body, { timeout: 60_000 }).toBe("first, then typed on a train, and while the signal was gone");
});

test("text typed but never saved (the line dropped, then the page was closed) is offered back when the draft is opened again", async ({ page }) => {
  test.setTimeout(240_000);
  const id = await matterWithPage(page);
  const d = await (await page.request.post("/api/drafts", { data: { matter_id: id, title: "Letter", body: "first" } })).json();
  await page.goto(`/drafts/${d.id}`);
  await expect(page.getByTestId("draft-status")).toContainText(/saved/i);
  await page.route("**/api/drafts/*", (r) => (r.request().method() === "PATCH" ? r.abort("internetdisconnected") : r.continue())); // the saves never reach the server
  await page.getByTestId("draft-editor-body").fill("text that only this phone has");
  await expect(page.getByTestId("draft-status")).toContainText(/kept on this (phone|device)|could not save/i, { timeout: 60_000 });
  await page.reload();
  await page.unroute("**/api/drafts/*");
  await page.route("**/api/drafts/*", (r) => (r.request().method() === "PATCH" ? r.abort("internetdisconnected") : r.continue()));
  await expect(page.getByTestId("draft-restore")).toBeVisible();
  await page.getByTestId("draft-restore-yes").click();
  await expect(page.getByTestId("draft-editor-body")).toHaveValue("text that only this phone has");
});

const ERRORS: [string, number | "offline", RegExp][] = [
  ["the line is cut", "offline", /check your (internet )?connection.*(try again|again)/i],
  ["the service is busy (503)", 503, /try again in a minute/i],
  ["something broke on the server (500)", 500, /try again/i],
  ["too many requests (429)", 429, /wait a moment.*try again/i],
];
for (const [label, how, expected] of ERRORS) {
  test(`when ${label}, asking a question says what to do next and keeps the question`, async ({ page }) => {
    await signUp(page);
    if (how !== "offline") await page.route("**/api/research", (r) => (r.request().method() === "POST" ? r.fulfill({ status: how, json: {} }) : r.continue()));
    await page.goto("/ask?q=Is a returned cheque an offence");
    if (how === "offline") await offline(page.context(), true);
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("ask-error")).toContainText(expected, { timeout: 30_000 });
    await expect(page.getByTestId("ask-input")).toHaveValue("Is a returned cheque an offence"); // nothing typed is lost
  });
}
