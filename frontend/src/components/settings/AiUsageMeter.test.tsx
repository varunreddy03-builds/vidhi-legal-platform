import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AiUsageMeter, { type AiUsage } from "./AiUsageMeter";

function render(data: AiUsage | undefined) {
  const qc = new QueryClient();
  if (data) qc.setQueryData(["ai-usage"], data);
  return renderToStaticMarkup(
    <QueryClientProvider client={qc}>
      <AiUsageMeter />
    </QueryClientProvider>,
  );
}

const pro: AiUsage = {
  plan: "pro",
  limits: [
    { name: "window", label: "5-hour", percent: 42.4, resets_at: "2026-11-05T15:00:00+00:00" },
    { name: "day", label: "day", percent: 100, resets_at: "2026-11-05T18:30:00+00:00" },
    { name: "week", label: "week", percent: 10, resets_at: "2026-11-08T18:30:00+00:00" },
    { name: "month", label: "month", percent: 2.5, resets_at: "2026-11-30T18:30:00+00:00" },
  ],
};

describe("AI use meter", () => {
  it("shows each limit as a labelled progress bar with a share and a renewal time, and says when a limit is reached", () => {
    const html = render(pro);
    for (const t of ["Every 5 hours", "Today", "This week", "This month"]) expect(html).toContain(t);
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('aria-valuenow="42"');
    expect(html).toContain("42% used");
    expect(html).toContain("Limit reached");
    expect(html).toContain("renews at");
    expect(html).toContain("renews on");
    expect((html.match(/role="progressbar"/g) ?? []).length).toBe(4);
    expect((html.match(/aria-labelledby="ai-usage-/g) ?? []).length).toBeGreaterThanOrEqual(5); // the section and every bar have a name
  });

  it("never shows money", () => {
    const html = render(pro);
    expect(html.toLowerCase()).not.toMatch(/₹|rs\.? ?\d|inr|rupee|usd|\$/);
  });

  it("a free person sees only their daily limit, in plain words", () => {
    const html = render({ plan: "free", limits: [{ name: "day", label: "day", percent: 0, resets_at: "2026-11-05T18:30:00+00:00" }] });
    expect(html).toContain("The free plan has a small AI allowance each day");
    expect(html).toContain("Today");
    expect(html).not.toContain("Every 5 hours");
  });

  it("shows nothing while there is nothing to show", () => {
    expect(render(undefined)).toBe("");
    expect(render({ plan: "pro", limits: [] })).toBe("");
  });
});
