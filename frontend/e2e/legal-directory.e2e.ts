import { expect, test } from "@playwright/test";
import { scan, signUp } from "./helpers";

// The courts and legal directory: it points to courts, official portals, law reports, court rules and legal aid bodies. A link is shown only when the server says the address was checked;
// a private publication (SCC, AIR) is named and never linked. The rules themselves are tested in backend/tests/test_legal_directory.py.

test("the legal directory lists courts and official sites, and finds a State's legal aid body", async ({ page }) => {
  await signUp(page);
  await page.goto("/legal-directory");
  await expect(page.getByTestId("dir-title")).toHaveText("Courts and legal directory");
  await expect(page.getByTestId("dir-note")).toContainText("not been reviewed by a lawyer");
  await expect(page.getByTestId("dir-note")).toContainText("last checked on");

  // courts: the Supreme Court has a checked official link that opens in a new tab and shows where it goes
  const sc = page.getByTestId("dir-link-court-supreme");
  await expect(sc).toHaveAttribute("href", /^https:\/\/www\.sci\.gov\.in\//);
  await expect(sc).toHaveAttribute("target", "_blank");
  await expect(sc).toHaveAttribute("rel", "noopener noreferrer");
  await expect(sc).toHaveText("sci.gov.in");
  await expect(page.getByTestId("dir-entry-court-jmsc")).toContainText("There is no such class today"); // the old Third Class of magistrates
  await expect(page.getByTestId("dir-entry-rev-tehsildar")).toBeVisible();

  // a private law report is named, labelled, and has no link
  const scc = page.getByTestId("dir-entry-jud-scc");
  await expect(scc).toContainText("private, not official");
  await expect(scc.locator("a")).toHaveCount(0);

  // legal aid: choose a State, see its authority as NALSA lists it
  await page.getByTestId("dir-state").selectOption("Telangana");
  const body = page.getByTestId("dir-state-body");
  await expect(body).toContainText("Telangana State Legal Services Authority");
  await expect(body).toContainText("As listed in NALSA's directory");
  await expect(page.getByTestId("dir-aid")).toContainText("does not represent anyone");
  await scan(page, "Legal directory with a State chosen");

  // search and section filter
  await page.getByTestId("dir-search").fill("consumer");
  await expect(page.getByTestId("dir-entry-trib-consumer")).toBeVisible();
  await expect(page.getByTestId("dir-entry-court-supreme")).toHaveCount(0);
  await page.getByTestId("dir-search").fill("zzznothing");
  await expect(page.getByTestId("dir-empty")).toBeVisible();
  await page.getByTestId("dir-search").fill("");
  await page.getByTestId("dir-section").selectOption("high_court_websites");
  await expect(page.getByTestId("dir-section-high_court_websites").locator("li")).toHaveCount(25);
});

test("the legal directory fits a phone screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signUp(page);
  await page.goto("/legal-directory");
  await expect(page.getByTestId("dir-title")).toBeVisible();
  await expect(page.getByTestId("dir-entry-court-supreme")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true); // no sideways scrolling
  await scan(page, "Legal directory on a phone");
});
