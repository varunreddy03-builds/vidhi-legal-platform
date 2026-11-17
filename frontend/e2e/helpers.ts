import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const unique = () => `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
export const newUser = () => ({ email: `e2e-${unique()}@example.com`, password: `E2e-${unique()}-Aa1`, name: "E2E Lawyer", org: `E2E Chambers ${unique()}` });

/** Sign up through the real form and land on the home screen. */
export async function signUp(page: Page, u = newUser()) {
  await page.goto("/login?mode=signup");
  await page.getByTestId("auth-fullname-input").fill(u.name);
  await page.getByTestId("auth-org-input").fill(u.org);
  await page.getByTestId("auth-email-input").fill(u.email);
  await page.getByTestId("auth-password-input").fill(u.password);
  await page.getByTestId("auth-privacy-checkbox").check();
  await page.waitForTimeout(1500); // without Turnstile the sign-up form refuses anything faster than a person could fill it in (1.2 s): that is the bot check working
  await page.getByTestId("auth-submit-button").click();
  await expect(page.getByTestId("start-greeting")).toBeVisible();
  return u;
}

/**
 * Accessibility scan (axe, WCAG 2.0/2.1 A and AA). Serious and critical problems fail the test, except colour contrast: the app's glass and
 * animated backgrounds make automatic contrast checks unreliable, so contrast is reported but needs a person with the design in front of them.
 */
export async function scan(page: Page, label: string) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = result.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""));
  const contrast = serious.filter((v) => v.id === "color-contrast");
  const blocking = serious.filter((v) => v.id !== "color-contrast");
  for (const v of blocking) console.log(`[axe] ${label}: ${v.id} (${v.impact}) - ${v.help}\n   ${v.nodes.slice(0, 4).map((n) => n.target.join(" ") + "  " + n.html.slice(0, 170).replace(/\s+/g, " ") + "  =>  " + (n.failureSummary ?? "").split("\n").slice(1, 3).join(" / ")).join("\n   ")}`);
  if (contrast.length) console.log(`[axe] ${label}: colour-contrast flagged on ${contrast[0].nodes.length} element(s) (reported, not failing)`);
  expect(blocking.map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`), `accessibility problems on ${label}`).toEqual([]);
}