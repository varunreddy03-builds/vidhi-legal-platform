import { expect, test } from "@playwright/test";
import { signUp } from "./helpers";

// Runs only against a server started with DEADLINE_ENGINE_ENABLED=true.
test.skip(process.env.DEADLINE_ENGINE_ENABLED !== "true", "The deadline engine is off on this server");

test("Deadline engine: with no reviewed rule loaded it says nothing can be calculated and shows no form", async ({ page }) => {
  await signUp(page);
  await page.goto("/katalyst");
  await expect(page.getByTestId("toolkit-deadlines-state")).toHaveText(/ready/i);
  await page.getByTestId("toolkit-deadlines").locator("a").click();
  await expect(page.getByTestId("dleng-notice")).toContainText("contains no limitation period or court rule of its own");
  await expect(page.getByTestId("dleng-none")).toContainText("No reviewed rule is loaded yet, so nothing can be calculated.");
  await expect(page.getByTestId("dleng-form")).toHaveCount(0); // no pretend calculator
});

// The platform-admin sign-in that enters a rule is not used by the browser tests, so these two answers are supplied; the real flow is tested on the server (test_deadlinerules_api.py).
const RULE = {
  id: "rule-1", title: "Invented rule: thirty days", starts_from: "the invented order date", period: { amount: 30, unit: "days" }, count_from: "day_after_start",
  when_not_working: "leave_as_is", not_applied: ["Invented: time spent obtaining a copy"], authorities: ["Invented source 1"], reviewed_by: "Adv Invented Reviewer", verified_on: "2026-10-20",
};

test("Deadline engine: pick a reviewed rule, see the due date with every step, the source, the reviewer and what is not applied, and copy it into My Dates", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.route("**/api/deadline-rules", (route) => route.fulfill({ json: { rules: [RULE], message: null } }));
  await page.route("**/api/deadline-rules/calculate", (route) =>
    route.fulfill({
      json: {
        due: "2031-04-02", weekday: "Wednesday", moved: false, start: "2031-03-03", rule: RULE, calendar: null,
        steps: ["Start date: 2031-03-03 (Monday).", "Added 30 days: 2031-04-02.", "The rule counts from the day after the start day, so nothing was taken back.", "The rule leaves the date as it is on a non-working day, so no calendar was used.", "Due date: 2031-04-02 (Wednesday)."],
        notice: "VIDHI applied only the rule shown below, as a person recorded it and a named reviewer checked it. It has not checked that the rule applies to your matter.",
      },
    }),
  );
  await signUp(page);
  await page.goto("/katalyst/deadlines");
  await expect(page.getByTestId("dleng-none")).toHaveCount(0);
  await page.getByTestId("dleng-rule-select").selectOption("rule-1");
  await expect(page.getByTestId("dleng-rule-sources")).toContainText("Invented source 1");
  await expect(page.getByTestId("dleng-rule-reviewer")).toContainText("Reviewed by Adv Invented Reviewer on 2026-10-20");
  await page.getByTestId("dleng-start").fill("2031-03-03");
  await page.getByTestId("dleng-run").click();

  await expect(page.getByTestId("dleng-due")).toContainText("2031-04-02");
  await expect(page.getByTestId("dleng-steps").locator("li")).toHaveCount(5);
  await expect(page.getByTestId("dleng-result").getByTestId("dleng-rule-not-applied")).toContainText("time spent obtaining a copy");
  await expect(page.getByTestId("dleng-result-notice")).toContainText("has not checked that the rule applies to your matter");
  await expect(page.getByText(/\bsafe to rely\b|\bwill be rejected\b|\blied\b/i)).toHaveCount(0);

  await page.getByTestId("dleng-add-open").click();
  await expect(page.getByTestId("dleng-add-date")).toHaveValue("2031-04-02");
  await page.getByTestId("dleng-add-title").fill("Reply due in the invented case");
  await page.getByTestId("dleng-add-submit").click();
  await expect(page.getByTestId("dleng-added")).toBeVisible();
  await page.goto("/deadlines");
  await expect(page.getByText("Reply due in the invented case")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
